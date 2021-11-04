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

import asyncio
import contextlib
import logging
from typing import Iterator
from typing import List

import fastapi
import libtorrent as lt

from .. import concurrency
from .. import ltmodels
from .. import ltpy
from .. import multihash
from .. import services

ROUTER = fastapi.APIRouter(prefix="/v1", tags=["torrent status"])

_LOG = logging.getLogger(__name__)


async def find_torrent_in(
    session: lt.session, btmh: multihash.Multihash
) -> lt.torrent_handle:
    if btmh.func != multihash.Func.sha1:
        raise fastapi.HTTPException(
            status_code=fastapi.status.HTTP_404_NOT_FOUND,
            detail="only sha1 info-hashes supported at this time",
        )
    sha1_hash = lt.sha1_hash(btmh.digest)
    return await concurrency.to_thread(session.find_torrent, sha1_hash)


async def find_torrent(btmh: multihash.Multihash) -> lt.torrent_handle:
    return await find_torrent_in(await services.get_session(), btmh)


@contextlib.contextmanager
def translate_exceptions() -> Iterator[None]:
    try:
        with ltpy.translate_exceptions():
            yield
    except ltpy.InvalidTorrentHandleError:
        raise fastapi.HTTPException(
            status_code=fastapi.status.HTTP_404_NOT_FOUND
        )


@ROUTER.get("/torrents")
async def get_torrents() -> List[ltmodels.TorrentStatus]:
    session = await services.get_session()
    with ltpy.translate_exceptions():
        handles = await concurrency.to_thread(session.get_torrents)
    status_list: List[ltmodels.TorrentStatus] = []
    aws = [concurrency.to_thread(h.status, flags=0x7FFFFFFF) for h in handles]
    tasks = [asyncio.create_task(aw) for aw in aws]
    try:
        for task in tasks:
            with contextlib.suppress(ltpy.InvalidTorrentHandleError):
                with ltpy.translate_exceptions():
                    status = ltmodels.TorrentStatus.from_orm(await task)
                status_list.append(status)
    finally:
        for task in tasks:
            task.cancel()
    return status_list


@ROUTER.get("/session/btmh/{btmh}")
async def status(btmh: multihash.Multihash) -> ltmodels.TorrentStatus:
    handle = await find_torrent(btmh)
    with translate_exceptions():
        return ltmodels.TorrentStatus.from_orm(
            await concurrency.to_thread(handle.status, flags=0x7FFFFF)
        )


@ROUTER.get("/session/btmh/{btmh}/piece_priorities")
async def get_piece_priorities(btmh: multihash.Multihash) -> List[int]:
    handle = await find_torrent(btmh)
    with translate_exceptions():
        return await concurrency.to_thread(handle.get_piece_priorities)


@ROUTER.delete("/session/btmh/{btmh}")
async def remove(btmh: multihash.Multihash) -> None:
    session = await services.get_session()
    handle = await find_torrent_in(session, btmh)
    with translate_exceptions():
        # NB: asynchronous, so not transactional
        session.remove_torrent(handle, option=lt.session.delete_files)
