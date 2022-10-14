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

import asyncio
from collections.abc import AsyncIterator
from collections.abc import Iterable
import contextlib
import functools

import anyio
import libtorrent as lt

from tvaf import ltpy


@contextlib.asynccontextmanager
async def wait_pieces(
    handle: lt.torrent_handle, pieces: Iterable[int], *, poll_interval: float
) -> AsyncIterator[AsyncIterator[int]]:
    # It would be nice to use piece_finished_alert here, but without constraints it may
    # flood the alert queue. For example, verifying a torrent with 16kb pieces on a
    # 3gb/s nvme could generate 196608 piece_finished_alerts per second
    # TODO: we could have a single poller per torrent
    have_piece: list[bool] = []
    piece_futures: dict[int, asyncio.Future] = {}
    get_status = functools.partial(handle.status, flags=lt.status_flags_t.query_pieces)

    async def poll() -> None:
        nonlocal have_piece
        while True:
            with ltpy.translate_exceptions():
                status = await asyncio.to_thread(get_status)
            prev_have_piece = have_piece
            have_piece = status.pieces
            if have_piece and not prev_have_piece:
                for piece in piece_futures:
                    if piece < 0 or piece >= len(have_piece):
                        raise IndexError(piece)
            if have_piece:
                just_got_pieces = [p for p in piece_futures if have_piece[p]]
                for piece in just_got_pieces:
                    piece_futures.pop(piece).set_result(None)
            await asyncio.sleep(poll_interval)

    async def iterator() -> AsyncIterator[int]:
        for piece in pieces:
            if not have_piece or not have_piece[piece]:
                if piece not in piece_futures:
                    piece_futures[piece] = asyncio.get_event_loop().create_future()
                await asyncio.shield(piece_futures[piece])
            yield piece

    async with anyio.create_task_group() as tasks:
        tasks.start_soon(poll)
        yield iterator()
        tasks.cancel_scope.cancel()
