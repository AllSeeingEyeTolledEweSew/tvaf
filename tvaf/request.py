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

"""Data access functions for tvaf."""

import asyncio
import collections
import contextlib
import logging
from typing import AsyncGenerator
from typing import cast
from typing import Dict
from typing import MutableMapping
from typing import Optional
from typing import Sequence
from typing import Set
import weakref

import libtorrent as lt

from . import concurrency
from . import driver as driver_lib
from . import ltpy

_LOG = logging.getLogger(__name__)


# set_piece_deadline() has very different behavior depending on the flags
# argument and the torrent's current state:
#
# - set_piece_deadline(i, x, alert_when_available):
#   - if we have piece i:
#     - ...is equivalent to read_piece(i)
#     - ...NOT idempotent, each call generates one read_piece_alert
#   - if we don't have piece i:
#     - ...sets the flag
#     - ...is idempotent
#
# - set_piece_deadline(i, x, 0):
#   - if we have piece i:
#     - ...has no effect
#   - if we don't have piece i:
#     - ...clears the flag
#     - ...if the flag was previously set, will fire alert with ECANCELED
#     - ...is idempotent

# set_piece_deadline(i, x) always stores the deadline internally as x +
# <current unix time in milliseconds>. Pieces are downloaded in deadline order,
# before any pieces without deadline. set_piece_deadline() always sets the
# piece priority to 7

# reset_piece_deadline() and clear_piece_deadlines() always set the priority
# of the given piece(s) to 1. If a piece is outstanding and has
# alert_when_available set, they will fire read_piece_alert with ECANCELED

# setting a piece's priority to 0 has the same effect as
# reset_piece_deadline(), except that the priority becomes 0 instead of 1

# Design notes: correspondence between read_piece_alert and futures/jobs is
# tricky. We could tighten it by tracking when we generate ECANCELED alerts by
# prioritizing from nonzero to zero, and propagate only unexpected errors. The
# upside is that we would respect external code that deprioritizes pieces.
# However we would be sensitive to an ECANCELED that was pending when we start
# up


class _State:
    SEQ_BUFFER = 30

    def __init__(self, handle: lt.torrent_handle, session: lt.session):
        self._handle = handle
        self._session = session
        # OrderdDict to preserve FIFO order for prioritizing requests
        self._reads: Dict[
            int, asyncio.Future[bytes]
        ] = collections.OrderedDict()
        self._readers: Dict[int, int] = {}
        self._prev_time_critical: Set[int] = set()

    def _delta_reads(self, prev: Set[int], cur: Set[int]) -> None:
        prioritize = False
        # Increment refcount for each new reading piece
        for piece in cur - prev:
            self._readers[piece] = self._readers.get(piece, 0) + 1
            if piece not in self._reads:
                self._reads[piece] = asyncio.get_event_loop().create_future()
                prioritize = True
        # Decrement refcount for each old reading piece
        for piece in prev - cur:
            self._readers[piece] -= 1
            assert self._readers[piece] >= 0
            if self._readers[piece] == 0:
                self._readers.pop(piece)
                future = self._reads.pop(piece)
                if not future.done():
                    prioritize = True
                else:
                    # mark as retrieved
                    future.exception()
        if prioritize:
            self.prioritize()

    # NB: This is a "naive" AsyncGenerator; pieces are prioritized in the
    # "setup" (first __anext__() call) and deprioritized in a finally clause.
    # This means that order of priorities between two read_pieces() calls is a
    # race, and deprioritization may be delayed until gc.
    async def read_pieces(
        self, pieces: Sequence[int]
    ) -> AsyncGenerator[bytes, None]:
        async def check() -> None:
            if not await concurrency.to_thread(
                ltpy.handle_in_session, self._handle, self._session
            ):
                self.set_exception(ltpy.InvalidTorrentHandleError.create())

        asyncio.create_task(check())

        # Do some once-per-stream setup
        with ltpy.translate_exceptions():
            # NB: some stuff here may generate alerts, so ensure we setup our
            # read futures before we await/yield
            self._handle.set_flags(
                lt.torrent_flags.auto_managed, lt.torrent_flags.auto_managed
            )
            # This will re-fire torrent_error_alert, if any, in lieu of polling
            # status()
            self._handle.clear_error()
        # NB: force_dht_announce is a no-op if the torrent is checking or
        # paused, so watch alerts and re-fire when leaving these states
        asyncio.create_task(self._maybe_dht_announce())

        # Design notes: I tried to write this as a simpler read_piece()
        # function, but that had to be synchronous to preserve order for
        # prioritization, and complex call usage is required to avoid holding
        # memory for the lifetime of a request
        prev_reading: Set[int] = set()

        try:
            for i, piece in enumerate(pieces):
                # Mark the next N pieces as reading
                reading = set(pieces[i : i + self.SEQ_BUFFER])
                self._delta_reads(prev_reading, reading)
                prev_reading = reading

                # Wait for the next piece to be read
                read = self._reads[piece]
                if read.done():
                    yield read.result()
                else:
                    start = asyncio.get_event_loop().time()
                    piece_data = await asyncio.shield(read)
                    elapsed = asyncio.get_event_loop().time() - start
                    _LOG.debug(
                        "%s piece %d: waited %dms",
                        str(self._handle.info_hash()),
                        piece,
                        int(elapsed * 1000),
                    )
                    yield piece_data
        finally:
            self._delta_reads(prev_reading, set())

    def prioritize(self) -> None:
        try:
            with ltpy.translate_exceptions():
                self._prioritize_inner()
        except BaseException as exc:
            self.set_exception(exc)

    def _prioritize_inner(self) -> None:
        time_critical = set(self._reads)

        for piece in time_critical - self._prev_time_critical:
            self._handle.set_piece_deadline(
                piece, 0, flags=lt.deadline_flags_t.alert_when_available
            )
        for piece in self._prev_time_critical - time_critical:
            self._handle.reset_piece_deadline(piece)

        self._prev_time_critical = time_critical

    def set_exception(self, exc: BaseException):
        for future in self._reads.values():
            if not future.done():
                future.set_exception(exc)

    def handle_alert(self, alert: lt.torrent_alert) -> None:
        if isinstance(alert, lt.read_piece_alert):
            future = self._reads.get(alert.piece)
            if future is None or future.done():
                return
            exc = ltpy.exception_from_error_code(alert.error)
            if exc:
                if isinstance(exc, ltpy.CanceledError):
                    self.prioritize()
                else:
                    future.set_exception(exc)
            else:
                future.set_result(alert.buffer)
        elif isinstance(alert, lt.torrent_removed_alert):
            self.set_exception(ltpy.InvalidTorrentHandleError.create())
        elif isinstance(alert, lt.torrent_error_alert):
            # These are mostly disk errors
            exc = ltpy.exception_from_error_code(alert.error)
            if exc is not None:
                self.set_exception(exc)
        elif isinstance(
            alert, (lt.torrent_checked_alert, lt.torrent_resumed_alert)
        ):
            # NB: libtorrent's current implementation will just queue the
            # torrent for the next session-wide dht announce cycle, which
            # defaults to 15 minutes!
            asyncio.create_task(self._maybe_dht_announce())

    async def _maybe_dht_announce(self) -> None:
        with contextlib.suppress(ltpy.InvalidTorrentHandleError):
            with ltpy.translate_exceptions():
                status = await concurrency.to_thread(self._handle.status)
                if status.num_peers == 0:
                    self._handle.force_dht_announce()

    # TODO: pause and resume

    # TODO: handle checking state

    # TODO: periodically reissue deadlines


class RequestService:
    def __init__(
        self, *, session: lt.session, alert_driver: driver_lib.AlertDriver
    ):
        self._session = session
        self._alert_driver = alert_driver
        self._states: MutableMapping[
            lt.torrent_handle, _State
        ] = weakref.WeakValueDictionary()
        self._closed = False
        self._task: Optional[asyncio.Future] = None

    def read_pieces(
        self, handle: lt.torrent_handle, pieces: Sequence[int]
    ) -> AsyncGenerator[bytes, None]:
        assert not self._closed
        state = self._states.get(handle)
        if not state:
            state = _State(handle, self._session)
            self._states[handle] = state
        return state.read_pieces(pieces)

    def start(self) -> None:
        assert self._task is None
        self._task = asyncio.create_task(self._run())

    def close(self) -> None:
        assert self._task is not None
        self._task.cancel()
        self._closed = True
        for state in self._states.values():
            state.set_exception(asyncio.CancelledError())

    async def wait_closed(self) -> None:
        assert self._closed
        assert self._task is not None
        with contextlib.suppress(asyncio.CancelledError):
            await self._task

    async def _run(self) -> None:
        with self._alert_driver.iter_alerts(
            lt.alert_category.status,
            lt.read_piece_alert,
            lt.torrent_removed_alert,
            lt.torrent_error_alert,
            lt.torrent_checked_alert,
            lt.torrent_resumed_alert,
        ) as iterator:
            # Do this here to ensure we capture alerts for any jobs started
            # before we created our iterator
            # Separate function to avoid references
            self._prioritize_all()
            async for alert in iterator:
                # Separate function to avoid references
                self._handle_alert(cast(lt.torrent_alert, alert))

    def _prioritize_all(self) -> None:
        for state in self._states.values():
            state.prioritize()

    def _handle_alert(self, alert: lt.torrent_alert) -> None:
        state = self._states.get(alert.handle)
        if state:
            state.handle_alert(alert)
