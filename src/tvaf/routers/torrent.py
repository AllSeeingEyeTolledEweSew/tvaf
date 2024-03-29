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
from collections.abc import Iterator
import contextlib
import logging

import anyio
import fastapi
import libtorrent as lt

from .. import ltmodels
from .. import ltpy
from .. import services

ROUTER = fastapi.APIRouter(prefix="/torrents", tags=["torrent status"])

_LOG = logging.getLogger(__name__)


async def find_torrent_in(session: lt.session, info_hash: bytes) -> lt.torrent_handle:
    best = ltmodels.info_hashes_from_digest(info_hash).get_best()
    return await asyncio.to_thread(session.find_torrent, best)


async def find_torrent(info_hash: bytes) -> lt.torrent_handle:
    session = await services.get_session()
    return await find_torrent_in(session, info_hash)


@contextlib.contextmanager
def translate_exceptions() -> Iterator[None]:
    try:
        with ltpy.translate_exceptions():
            yield
    except ltpy.InvalidTorrentHandleError:
        raise fastapi.HTTPException(status_code=fastapi.status.HTTP_404_NOT_FOUND)


@ROUTER.get("/")
async def get_torrents() -> list[ltmodels.TorrentStatus]:
    session = await services.get_session()
    with ltpy.translate_exceptions():
        handles = await asyncio.to_thread(session.get_torrents)
    index_to_status_model: dict[int, ltmodels.TorrentStatus] = {}

    async def fetch_one_status(index: int, handle: lt.torrent_handle) -> None:
        with contextlib.suppress(ltpy.InvalidTorrentHandleError):
            with ltpy.translate_exceptions():
                status = await asyncio.to_thread(handle.status, flags=0x7FFFFFFF)
        index_to_status_model[index] = ltmodels.TorrentStatus.from_orm(status)

    async with anyio.create_task_group() as tasks:
        for index, handle in enumerate(handles):
            tasks.start_soon(fetch_one_status, index, handle)
    return [status for _, status in sorted(index_to_status_model.items())]


@ROUTER.get("/{info_hash}")
async def status(info_hash: ltmodels.Hex160) -> ltmodels.TorrentStatus:
    handle = await find_torrent(info_hash)
    with translate_exceptions():
        return ltmodels.TorrentStatus.from_orm(
            await asyncio.to_thread(handle.status, flags=0x7FFFFF)
        )


@ROUTER.get("/{info_hash}/piece_priorities")
async def get_piece_priorities(
    info_hash: ltmodels.Hex160,
) -> list[int]:
    handle = await find_torrent(info_hash)
    with translate_exceptions():
        return await asyncio.to_thread(handle.get_piece_priorities)


@ROUTER.delete("/{info_hash}")
async def remove(info_hash: ltmodels.Hex160) -> None:
    session = await services.get_session()
    handle = await find_torrent_in(session, info_hash)
    with translate_exceptions():
        # NB: asynchronous, so not transactional
        session.remove_torrent(handle, option=lt.session.delete_files)
