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

import contextlib
import logging
from typing import Iterator

import fastapi
import libtorrent as lt

from .. import concurrency
from .. import ltmodels
from .. import ltpy
from .. import multihash
from .. import services

ROUTER = fastapi.APIRouter(prefix="/v1", tags=["torrent status"])

_LOG = logging.getLogger(__name__)


async def find_torrent(
    session: lt.session, btmh: multihash.Multihash
) -> lt.torrent_handle:
    if btmh.func != multihash.Func.sha1:
        raise fastapi.HTTPException(
            status_code=fastapi.status.HTTP_404_NOT_FOUND,
            detail="only sha1 info-hashes supported at this time",
        )
    sha1_hash = lt.sha1_hash(btmh.digest)
    return await concurrency.to_thread(session.find_torrent, sha1_hash)


@contextlib.contextmanager
def translate_exceptions() -> Iterator[None]:
    try:
        with ltpy.translate_exceptions():
            yield
    except ltpy.InvalidTorrentHandleError:
        raise fastapi.HTTPException(
            status_code=fastapi.status.HTTP_404_NOT_FOUND
        )


@ROUTER.get("/session/btmh/{btmh}")
async def status(btmh: multihash.Multihash) -> ltmodels.TorrentStatus:
    handle = await find_torrent(await services.get_session(), btmh)
    with translate_exceptions():
        status = await concurrency.to_thread(
            handle.status, flags=lt.status_flags_t.query_pieces
        )
        piece_priorities = await concurrency.to_thread(
            handle.get_piece_priorities
        )
    return ltmodels.TorrentStatus(
        pieces=ltmodels.seq_to_bitfield64(status.pieces),
        piece_priorities=piece_priorities,
    )


@ROUTER.delete("/session/btmh/{btmh}")
async def remove(btmh: multihash.Multihash) -> None:
    session = await services.get_session()
    handle = await find_torrent(session, btmh)
    with translate_exceptions():
        # NB: asynchronous, so not transactional
        session.remove_torrent(handle, option=lt.session.delete_files)
