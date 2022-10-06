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
from collections.abc import AsyncIterable
from collections.abc import AsyncIterator
from collections.abc import Coroutine
from collections.abc import Iterator
from collections.abc import Sequence
import contextlib
import errno
from typing import Any
from typing import Callable
from typing import cast
from typing import Optional
import weakref

import anyio
import libtorrent as lt

from tvaf import driver as driver_lib
from tvaf import ltpy


class ReadPrioritizer:
    SEQ_BUFFER = 30

    def __init__(self, handle: lt.torrent_handle):
        self._handle = handle
        self._refcount: dict[int, int] = {}

    def _delta_reads(self, dec: set[int], inc: set[int]) -> None:
        # TODO: assign time critical pieces in reasonable order
        with ltpy.translate_exceptions():
            for piece in inc - dec:
                current = self._refcount.get(piece, 0)
                if current == 0:
                    self._handle.set_piece_deadline(piece, 0)
                self._refcount[piece] = current + 1
            for piece in dec - inc:
                current = self._refcount[piece]
                assert current > 0
                if current == 1:
                    self._handle.reset_piece_deadline(piece)
                    self._refcount.pop(piece)
                else:
                    self._refcount[piece] = current - 1

    @contextlib.contextmanager
    def read_pieces(self, pieces: Sequence[int]) -> Iterator[Iterator[int]]:
        reset_on_exit = True
        prev_reading: set[int] = set()

        def iterator() -> Iterator[int]:
            nonlocal prev_reading
            for i, piece in enumerate(pieces):
                reading = set(pieces[i : i + self.SEQ_BUFFER])
                self._delta_reads(prev_reading, reading)
                prev_reading = reading
                yield piece

        try:
            yield iterator()
        except ltpy.InvalidTorrentHandleError:
            reset_on_exit = False
            raise
        finally:
            if reset_on_exit:
                self._delta_reads(prev_reading, set())


@contextlib.asynccontextmanager
async def _neutral_semaphore(
    semaphore: asyncio.Semaphore,
) -> AsyncIterator[tuple[Callable[[], Coroutine[Any, Any, None]], Callable[[], None]]]:
    acquires = 0

    async def tracked_acquire() -> None:
        await semaphore.acquire()
        nonlocal acquires
        acquires += 1

    def tracked_release() -> None:
        semaphore.release()
        nonlocal acquires
        acquires -= 1

    try:
        yield tracked_acquire, tracked_release
    finally:
        for _ in range(acquires):
            semaphore.release()
        for _ in range(-acquires):
            await semaphore.acquire()


class PieceBytesReader:
    def __init__(
        self, *, alert_limiter: asyncio.Semaphore, iter_alerts: driver_lib.IterAlerts
    ) -> None:
        self._alert_limiter = alert_limiter
        self._iter_alerts = iter_alerts

    @contextlib.asynccontextmanager
    async def read(
        self, *, handle: lt.torrent_handle, pieces: AsyncIterable[int], queue_size: int
    ) -> AsyncIterator[AsyncIterator[bytes]]:
        futures: weakref.WeakValueDictionary[
            int, asyncio.Future[bytes]
        ] = weakref.WeakValueDictionary()
        queue: asyncio.Queue[Optional[asyncio.Future[bytes]]] = asyncio.Queue(
            queue_size
        )

        async def iterator() -> AsyncIterator[bytes]:
            while True:
                data_future = await queue.get()
                if data_future is None:
                    break
                data = await data_future
                yield data

        async with contextlib.AsyncExitStack() as stack:
            acquire, release = await stack.enter_async_context(
                _neutral_semaphore(self._alert_limiter)
            )
            alerts = await stack.enter_async_context(
                self._iter_alerts(0, lt.read_piece_alert, handle=handle)
            )
            tasks = await stack.enter_async_context(anyio.create_task_group())

            async def handle_alerts() -> None:
                async for base_alert in alerts:
                    alert = cast(lt.read_piece_alert, base_alert)
                    future = futures.get(alert.piece)
                    if future is None or future.done():
                        continue
                    # This can't happen with read_piece(), so it must be from other code
                    if (alert.error.category(), alert.error.value()) == (
                        lt.generic_category(),
                        errno.ECANCELED,
                    ):
                        continue
                    exc = ltpy.exception_from_error_code(alert.error)
                    if exc is not None:
                        raise exc
                    release()
                    future.set_result(alert.buffer)

            async def feed_queue() -> None:
                async for piece in pieces:
                    future = futures.get(piece)
                    if future is None:
                        future = asyncio.get_event_loop().create_future()
                        futures[piece] = future
                    await queue.put(future)
                    if not future.done():
                        await acquire()
                        with ltpy.translate_exceptions():
                            handle.read_piece(piece)
                await queue.put(None)

            tasks.start_soon(handle_alerts)
            tasks.start_soon(feed_queue)
            yield iterator()
            tasks.cancel_scope.cancel()
