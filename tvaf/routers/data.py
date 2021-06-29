# Copyright (c) 2021 AllSeeingEyeTolledEweSew
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

import logging
from typing import AsyncIterator
from typing import Awaitable
from typing import Callable
from typing import Iterator
from typing import Optional
from typing import Sequence
from typing import Tuple
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
from .. import ltpy
from .. import multihash
from .. import services
from .. import torrent_info
from .. import util
from ..services import util as services_util

ROUTER = fastapi.APIRouter(prefix="/v1", tags=["data access"])

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


def _get_bounds_from_ti(
    ti: lt.torrent_info, file_index: int
) -> Tuple[int, int]:
    fs = ti.files()
    if file_index >= fs.num_files():
        raise IndexError(file_index)
    offset = fs.file_offset(file_index)
    size = fs.file_size(file_index)
    return (offset, offset + size)


class _Helper:
    def __init__(self, btmh: multihash.Multihash, file_index: int) -> None:
        self.btmh = btmh
        self.file_index = file_index

    @concurrency.acached_property
    async def existing_handle(self) -> lt.torrent_handle:
        assert self.btmh.func == multihash.Func.sha1
        sha1_hash = lt.sha1_hash(self.btmh.digest)
        session = await services.get_session()
        return await concurrency.to_thread(session.find_torrent, sha1_hash)

    @concurrency.acached_property
    async def existing_torrent_info(self) -> Optional[lt.torrent_info]:
        handle = await self.existing_handle
        if not handle.is_valid():
            return None
        return await concurrency.to_thread(handle.torrent_file)

    @concurrency.acached_property
    async def torrent_info(self) -> lt.torrent_info:
        return await services_util.get_torrent_info(await self.valid_handle)

    @concurrency.acached_property
    async def bounds(self) -> Tuple[int, int]:
        try:
            # If the torrent exists and has metadata, get bounds from that
            existing_ti = await self.existing_torrent_info
            if existing_ti:
                return _get_bounds_from_ti(existing_ti, self.file_index)

            # Get bounds from cache
            try:
                return await torrent_info.get_file_bounds_from_cache(
                    self.btmh, self.file_index
                )
            except KeyError:
                pass

            # Add the torrent and get bounds from its metadata
            return _get_bounds_from_ti(
                await self.torrent_info, self.file_index
            )
        except IndexError:
            raise fastapi.HTTPException(
                status_code=fastapi.status.HTTP_404_NOT_FOUND,
                detail="file does not exist in torrent",
            )

    @concurrency.acached_property
    async def configure_atp(
        self,
    ) -> Callable[[lt.add_torrent_params], Awaitable]:
        try:
            return await torrent_info.get_configure_atp(self.btmh)
        except KeyError:
            raise fastapi.HTTPException(
                status_code=fastapi.status.HTTP_404_NOT_FOUND,
                detail="unknown torrent",
            )

    @concurrency.acached_property
    async def valid_handle(self) -> lt.torrent_handle:
        existing = await self.existing_handle
        if existing.is_valid():
            return existing
        configure_atp = await self.configure_atp
        atp = await services.get_default_atp()
        await configure_atp(atp)
        await services.configure_atp(atp)
        atp.flags &= ~lt.torrent_flags.duplicate_is_error
        session = await services.get_session()
        # TODO: check against the requested network
        with ltpy.translate_exceptions():
            return await concurrency.to_thread(session.add_torrent, atp)


@ROUTER.api_route("/btmh/{btmh}/i/{file_index}", methods=["GET", "HEAD"])
async def read_file(
    btmh: multihash.Multihash,
    file_index: NonNegativeInt,
    request: fastapi.Request,
):
    if btmh.func != multihash.Func.sha1:
        raise fastapi.HTTPException(
            status_code=fastapi.status.HTTP_404_NOT_FOUND,
            detail="only sha1 info-hashes supported at this time",
        )

    helper = _Helper(btmh, file_index)
    # May add the torrent, to figure out bounds from its torrent_info
    start, stop = await helper.bounds
    length = stop - start
    # Do this even for HEAD requests, to ensure we can access the torrent
    await helper.configure_atp

    status_code = fastapi.status.HTTP_200_OK
    etag = f'"{btmh}.{file_index}"'
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
        start_piece, stop_piece = util.range_to_pieces(
            piece_length, start, stop
        )
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
