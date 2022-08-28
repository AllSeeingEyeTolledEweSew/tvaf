# Copyright (c) 2022 AllSeeingEyeTolledEweSew
#
# Permission to use, copy, modify, and/or distribute this software for any
# purpose with or without fee is hereby granted.
#
# THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES WITH
# REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF MERCHANTABILITY
# AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY SPECIAL, DIRECT,
# INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES WHATSOEVER RESULTING FROM
# LOSS OF USE, DATA OR PROFITS, WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE OR
# OTHER TORTIOUS ACTION, ARISING OUT OF OR IN CONNECTION WITH THE USE OR
# PERFORMANCE OF THIS SOFTWARE.

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from collections.abc import Iterator
from collections.abc import Sequence
import logging
from typing import Optional
from typing import TypeVar
from typing import Union

import fastapi
import libtorrent as lt
from pydantic import NonNegativeInt
from starlette.datastructures import Headers
from starlette.datastructures import MutableHeaders
import starlette.responses
import starlette.types

from .. import byteranges
from .. import concurrency
from .. import ltmodels
from .. import ltpy
from .. import services
from .. import swarm
from .. import torrent_info
from .. import util
from ..services import atp as atp_services
from ..services import util as services_util

ROUTER = fastapi.APIRouter(prefix="/d", tags=["data access"])

_LOG = logging.getLogger(__name__)


# from starlette.staticfiles, which requires aiofiles to even import
class NotModifiedResponse(starlette.responses.Response):
    NOT_MODIFIED_HEADERS = (
        "cache-control",
        "content-location",
        "date",
        "etag",
        "expires",
        "vary",
    )

    def __init__(self, headers: Headers) -> None:
        super().__init__(
            status_code=304,
            headers={
                name: value
                for name, value in headers.items()
                if name in self.NOT_MODIFIED_HEADERS
            },
        )


_T = TypeVar("_T")


def _get_bounds_from_ti(ti: lt.torrent_info, file_index: int) -> tuple[int, int]:
    fs = ti.files()
    if file_index >= fs.num_files():
        raise IndexError(file_index)
    offset = fs.file_offset(file_index)
    size = fs.file_size(file_index)
    return (offset, offset + size)


class _Helper:
    def __init__(self, info_hashes: lt.info_hash_t, file_index: int) -> None:
        self.info_hashes = info_hashes
        self.file_index = file_index

    @concurrency.acached_property
    async def existing_handle(self) -> lt.torrent_handle:
        session = await services.get_session()
        return await asyncio.to_thread(
            session.find_torrent, self.info_hashes.get_best()
        )

    @concurrency.acached_property
    async def existing_torrent_info(self) -> Optional[lt.torrent_info]:
        handle = await self.existing_handle
        if not handle.is_valid():
            return None
        return await asyncio.to_thread(handle.torrent_file)

    @concurrency.acached_property
    async def torrent_info(self) -> lt.torrent_info:
        return await services_util.get_torrent_info(await self.valid_handle)

    @concurrency.acached_property
    async def bounds(self) -> tuple[int, int]:
        try:
            # If the torrent exists and has metadata, get bounds from that
            existing_ti = await self.existing_torrent_info
            if existing_ti:
                return _get_bounds_from_ti(existing_ti, self.file_index)

            # Get bounds from cache
            try:
                return await torrent_info.map_file(self.info_hashes, self.file_index)
            except KeyError:
                pass

            # Add the torrent and get bounds from its metadata
            return _get_bounds_from_ti(await self.torrent_info, self.file_index)
        except IndexError:
            raise fastapi.HTTPException(
                status_code=fastapi.status.HTTP_404_NOT_FOUND,
                detail="file does not exist in torrent",
            )

    @concurrency.acached_property
    async def configure_swarm(
        self,
    ) -> swarm.ConfigureSwarm:
        name_to_configure_swarm = await swarm.get_name_to_configure_swarm(
            self.info_hashes
        )
        if not name_to_configure_swarm:
            raise fastapi.HTTPException(
                status_code=fastapi.status.HTTP_404_NOT_FOUND,
                detail="unknown torrent",
            )
        return list(name_to_configure_swarm.values())[0]

    @concurrency.acached_property
    async def valid_handle(self) -> lt.torrent_handle:
        existing = await self.existing_handle
        if existing.is_valid():
            return existing
        configure_swarm = await self.configure_swarm
        atp = await atp_services.get_default()
        atp.info_hashes = self.info_hashes
        await configure_swarm(atp)
        await atp_services.configure(atp)
        atp.flags &= ~lt.torrent_flags.duplicate_is_error
        session = await services.get_session()
        # TODO: check against the requested network
        with ltpy.translate_exceptions():
            return await asyncio.to_thread(session.add_torrent, atp)  # type: ignore


@ROUTER.api_route("/btih/{info_hash}/i/{file_index}", methods=["GET", "HEAD"])
async def read_file(
    info_hash: ltmodels.Hex160,
    file_index: NonNegativeInt,
    request: fastapi.Request,
):
    helper = _Helper(ltmodels.info_hashes_from_digest(info_hash), file_index)
    # May add the torrent, to figure out bounds from its torrent_info
    start, stop = await helper.bounds
    length = stop - start

    status_code = fastapi.status.HTTP_200_OK
    etag = f'"{info_hash.hex()}.{file_index}"'
    headers = MutableHeaders(
        {
            "Content-Type": "application/octet-stream",
            "Content-Length": str(length),
            "Accept-Ranges": "bytes",
            "etag": etag,
            "cache-control": "public, immutable, max-age=31536000",
        }
    )

    if request.headers.get("if-none-match", "") == etag:
        return NotModifiedResponse(headers)

    slices: Sequence[slice] = []
    if "range" in request.headers:
        if request.headers.get("if-range", etag) == etag:
            try:
                slices = byteranges.parse_bytes_range(request.headers["range"])
            except ValueError:
                pass
    if len(slices) == 1:
        range_start, range_stop, _ = slices[0].indices(length)
        if range_start >= length:
            headers["content-range"] = f"bytes */{length}"
            headers["content-length"] = "0"
            raise fastapi.HTTPException(
                status_code=416,
                headers=dict(headers),
                detail="requested range does not overlap file bounds",
            )
        status_code = fastapi.status.HTTP_206_PARTIAL_CONTENT
        content_range = f"bytes {range_start}-{range_stop - 1}/{length}"
        headers["content-range"] = content_range
        headers["content-length"] = str(range_stop - range_start)
        start, stop = start + range_start, start + range_stop

    iterator: Union[AsyncIterator[bytes], Iterator[bytes]] = iter(())
    if request.method == "GET":
        # Will add the torrent if it hasn't been added yet
        piece_length = (await helper.torrent_info).piece_length()
        start_piece, stop_piece = util.range_to_pieces(piece_length, start, stop)
        request_service = await services.get_request_service()
        pieces = request_service.read_pieces(
            await helper.valid_handle, range(start_piece, stop_piece)
        )

        async def clamped_pieces() -> AsyncIterator[bytes]:
            offset = start_piece * piece_length
            async for piece in pieces:
                assert offset < stop
                lo = max(0, start - offset)
                hi = min(len(piece), stop - offset)
                yield piece[lo:hi]
                offset += len(piece)

        iterator = clamped_pieces()

    return starlette.responses.StreamingResponse(
        iterator, status_code=status_code, headers=dict(headers)
    )
