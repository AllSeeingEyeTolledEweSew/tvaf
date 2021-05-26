# Copyright (c) 2020 AllSeeingEyeTolledEweSew
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

import collections
import collections.abc
import enum
import errno
import logging
import threading
from typing import Dict
from typing import Iterable
from typing import Optional
from typing import Set
from weakref import WeakValueDictionary

import libtorrent as lt

from tvaf import driver as driver_lib
from tvaf import ltpy
from tvaf import resume as resume_lib
from tvaf import task as task_lib
from tvaf import util
from tvaf import xmemoryview as xmv

_LOG = logging.getLogger(__name__)

DEFAULT_DOWNLOAD_DIR_NAME = "downloads"


def _mk_cancelederror() -> ltpy.CanceledError:
    return ltpy.CanceledError(
        lt.error_code(errno.ECANCELED, lt.generic_category())
    )


class Mode(enum.Enum):

    READ = "read"
    READAHEAD = "readahead"


class Request:
    def __init__(
        self,
        *,
        handle: lt.torrent_handle,
        start: int,
        stop: int,
        mode: Mode,
    ):
        self.handle = handle
        self.start = start
        self.stop = stop
        self.mode = mode

        self._condition = threading.Condition()
        self._chunks: Dict[int, xmv.MemoryView] = {}
        self._offset = self.start
        self._exception: Optional[BaseException] = None

    def set_exception(self, exception: BaseException) -> None:
        with self._condition:
            self._exception = exception
            self._condition.notify_all()

    def feed_chunk(self, offset: int, chunk: xmv.MemoryView) -> None:
        if self.mode != Mode.READ:
            raise ValueError("not a read request")
        with self._condition:
            if offset < self.start:
                chunk = chunk[self.start - offset :]
                offset = self.start
            if offset + len(chunk) > self.stop:
                chunk = chunk[: self.stop - offset]
            if not chunk:
                return
            self._chunks[offset] = chunk
            self._condition.notify_all()

    def tell(self) -> int:
        with self._condition:
            return self._offset

    def read(self, timeout: float = None) -> Optional[xmv.MemoryView]:
        if self.mode != Mode.READ:
            raise ValueError("not a read request")
        with self._condition:
            if self._offset >= self.stop:
                return xmv.EMPTY

            def ready() -> bool:
                if self._offset in self._chunks:
                    return True
                if self._exception is not None:
                    return True
                return False

            if not self._condition.wait_for(ready, timeout=timeout):
                return None
            if self._exception:
                raise self._exception
            chunk = self._chunks.pop(self._offset)
            self._offset += len(chunk)
            return chunk


def _get_request_pieces(
    request: Request, ti: lt.torrent_info
) -> Iterable[int]:
    return iter(
        range(
            *util.range_to_pieces(
                ti.piece_length(), request.start, request.stop
            )
        )
    )


class _State:

    DEADLINE_INTERVAL = 1000

    def __init__(self, handle: lt.torrent_handle):
        self._handle = handle
        self._ti: Optional[lt.torrent_info] = None
        # OrderedDict is to preserve FIFO order for satisfying requests. We use
        # a mapping like {id(obj): obj} to emulate an ordered set
        # NB: As of 3.8, OrderedDict is not subscriptable
        self._requests = (
            collections.OrderedDict()
        )  # type: collections.OrderedDict[int, Request]

        self._piece_to_readers: Dict[int, Set[Request]] = {}
        # NB: As of 3.8, OrderedDict is not subscriptable
        self._piece_queue = (
            collections.OrderedDict()
        )  # type: collections.OrderedDict[int, int]

        self._exception: Optional[BaseException] = None

    def _get_request_pieces(self, request: Request) -> Iterable[int]:
        assert self._ti is not None
        return _get_request_pieces(request, self._ti)

    def _index_request(self, request: Request) -> None:
        if self._ti is None:
            return
        if request.mode != Mode.READ:
            return
        for piece in self._get_request_pieces(request):
            if piece not in self._piece_to_readers:
                self._piece_to_readers[piece] = set()
            self._piece_to_readers[piece].add(request)

    def add(self, *requests: Request) -> None:
        for request in requests:
            self._requests[id(request)] = request
            self._index_request(request)

    def _deindex_request(self, request: Request) -> None:
        if self._ti is None:
            return
        if request.mode != Mode.READ:
            return
        for piece in self._get_request_pieces(request):
            readers = self._piece_to_readers.get(piece, set())
            readers.discard(request)
            if not readers:
                self._piece_to_readers.pop(piece, None)

    def discard(self, *requests: Request, exception: BaseException) -> None:
        for request in requests:
            request.set_exception(exception)
            self._requests.pop(id(request))
            self._deindex_request(request)

    def get_ti(self) -> Optional[lt.torrent_info]:
        return self._ti

    def set_ti(self, ti: lt.torrent_info) -> None:
        if self._ti is not None:
            return
        self._ti = ti
        for request in list(self._requests.values()):
            self._index_request(request)

    def update_priorities(self) -> None:
        if self._ti is None:
            return

        self._piece_queue.clear()

        for request in self._requests.values():
            if request.mode != Mode.READ:
                continue
            for piece in self._get_request_pieces(request):
                if piece not in self._piece_queue:
                    self._piece_queue[piece] = piece

        for request in self._requests.values():
            if request.mode != Mode.READAHEAD:
                continue
            for piece in self._get_request_pieces(request):
                if piece not in self._piece_queue:
                    self._piece_queue[piece] = piece

        self._apply_priorities()

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
    # <current unix time in milliseconds>. Pieces are downloaded in deadline
    # order, before any pieces without deadline. set_piece_deadline() always
    # sets the piece priority to 7

    # reset_piece_deadline() and clear_piece_deadlines() always set the
    # priority of the given piece(s) to 1. If a piece is outstanding and has
    # alert_when_available set, they will fire read_piece_alert with ECANCELED

    # setting a piece's priority to 0 has the same effect as
    # reset_piece_deadline(), except that the priority becomes 0 instead of 1

    def _apply_priorities_inner(self) -> None:
        if self._ti is None:
            return

        if self._piece_queue:
            self._handle.set_flags(
                lt.torrent_flags.auto_managed, lt.torrent_flags.auto_managed
            )

        priorities = [0] * self._ti.num_pieces()

        # Update deadlines in reverse order, to avoid a temporary state where
        # the existing deadline of a last-priority piece is earlier than the
        # new deadline of a first-priority piece
        for seq, piece in enumerate(reversed(self._piece_queue)):
            seq = len(self._piece_queue) - seq - 1
            # We want a read_piece_alert if there are any outstanding
            # readers
            want_read = piece in self._piece_to_readers
            if want_read:
                flags = lt.deadline_flags_t.alert_when_available
            else:
                flags = 0
            # Space out the deadline values, so the advancement of unix time
            # doesn't interfere with our queue order
            deadline = seq * self.DEADLINE_INTERVAL
            self._handle.set_piece_deadline(piece, deadline, flags=flags)
            priorities[piece] = 7

        self._handle.prioritize_pieces(priorities)

    def _apply_priorities(self) -> None:
        with ltpy.translate_exceptions():
            self._apply_priorities_inner()

    def on_read_piece(
        self, piece: int, data: bytes, exception: Optional[BaseException]
    ) -> None:
        readers = self._piece_to_readers.get(piece, ())
        if not readers:
            return
        if isinstance(exception, ltpy.CanceledError):
            self._apply_priorities()
            return
        del self._piece_to_readers[piece]
        if exception is not None:
            self.discard(*readers, exception=exception)
        else:
            assert self._ti is not None

            chunk = xmv.MemoryView(obj=data, start=0, stop=len(data))
            offset = piece * self._ti.piece_length()

            for reader in readers:
                reader.feed_chunk(offset, chunk)

    def set_exception(self, exception: BaseException) -> None:
        self.discard(*self._requests.values(), exception=exception)
        self._exception = exception

    def get_exception(self) -> Optional[BaseException]:
        return self._exception

    def has_requests(self) -> bool:
        return bool(self._requests)

    # TODO: pause and resume

    # TODO: baseline priorities

    # TODO: handle checking state

    # TODO: periodically reissue deadlines


class _Task(task_lib.Task):
    # NB: after the last request is removed, we must no longer mutate the
    # torrent. To achieve this, only mutate the torrent with the lock held.
    def __init__(
        self,
        *,
        handle: lt.torrent_handle,
        alert_driver: driver_lib.AlertDriver,
        resume_service: resume_lib.ResumeService,
    ):
        super().__init__(title=f"request handler for {handle.info_hash()}")
        self._handle = handle
        self._resume_service = resume_service

        self._state = _State(handle)
        # The proper place for this is after iterator creation, so we don't
        # miss a metadata_received_alert, but this would block alert
        # processing. We could always get it from save_resume_data_alert, but
        # this adds extra alert processing. So we do *both*: get torrent_info
        # now for efficiency in the common case, and fire save_resume_data for
        # correctness.
        # DOES block
        ti = handle.torrent_file()
        if ti is not None:
            self._state.set_ti(ti)
        self._iterator = alert_driver.iter_alerts(
            lt.alert_category.status,
            lt.read_piece_alert,
            lt.torrent_removed_alert,
            lt.save_resume_data_alert,
            lt.torrent_error_alert,
            lt.metadata_received_alert,
            handle=handle,
        )

    def add(self, *requests: Request) -> bool:
        with self._lock:
            if self._terminated.is_set():
                return False
            self._state.add(*requests)
            self._state.update_priorities()
            return True

    def discard(self, *requests: Request) -> None:
        with self._lock:
            self._state.discard(
                *requests,
                exception=_mk_cancelederror(),
            )
            self._state.update_priorities()
            if not self._state.has_requests():
                self.terminate()

    def _set_exception(self, exception: BaseException) -> None:
        with self._lock:
            super()._set_exception(exception)
            self._state.set_exception(exception)
            self._state.update_priorities()

    def _terminate(self) -> None:
        with self._lock:
            self._iterator.close()
            # Normal termination still terminates requests (but doesn't count
            # as the task canceling abnormally)
            if self._state.get_exception() is None:
                self._state.set_exception(_mk_cancelederror())
                self._state.update_priorities()

    def _handle_alert_locked(self, alert: lt.alert) -> None:
        if isinstance(alert, lt.read_piece_alert):
            exc = ltpy.exception_from_error_code(alert.error)
            self._state.on_read_piece(alert.piece, alert.buffer, exc)
        elif isinstance(alert, lt.torrent_removed_alert):
            raise ltpy.InvalidTorrentHandleError(
                lt.error_code(
                    ltpy.LibtorrentErrorValue.INVALID_TORRENT_HANDLE,
                    lt.libtorrent_category(),
                )
            )
        elif isinstance(alert, lt.save_resume_data_alert):
            if alert.params.ti is not None:
                self._state.set_ti(alert.params.ti)
                self._state.update_priorities()
        elif isinstance(alert, lt.torrent_error_alert):
            # These are mostly disk errors
            exc = ltpy.exception_from_error_code(alert.error)
            if exc is not None:
                raise exc
        elif isinstance(alert, lt.metadata_received_alert):
            self._resume_service.save(
                alert.handle, flags=lt.torrent_handle.save_info_dict
            )

    def _run(self) -> None:
        with self._iterator:
            with self._lock:
                if self._terminated.is_set():
                    return

                with ltpy.translate_exceptions():
                    # This will re-fire any error alerts
                    # Does not block
                    self._handle.clear_error()

                self._state.update_priorities()

                # See comment in constructor
                if self._state.get_ti() is None:
                    self._resume_service.save(
                        self._handle, flags=lt.torrent_handle.save_info_dict
                    )

            for alert in self._iterator:
                with self._lock:
                    if self._terminated.is_set():
                        return
                    self._handle_alert_locked(alert)


class RequestService(task_lib.Task):
    def __init__(
        self,
        *,
        alert_driver: driver_lib.AlertDriver,
        resume_service: resume_lib.ResumeService,
        pedantic=False,
    ):
        super().__init__(title="RequestService", thread_name="request")
        self._alert_driver = alert_driver
        self._resume_service = resume_service
        self._pedantic = pedantic

        self._lock = threading.RLock()
        # As of 3.8, WeakValueDictionary is unsubscriptable
        self._tasks = (
            WeakValueDictionary()
        )  # type: WeakValueDictionary[lt.torrent_handle, _Task]

    def add_request(
        self,
        *,
        handle: lt.torrent_handle,
        start: int,
        stop: int,
        mode: Mode,
    ) -> Request:
        request = Request(
            handle=handle,
            start=start,
            stop=stop,
            mode=mode,
        )

        with self._lock:
            if self._terminated.is_set():
                request.set_exception(_mk_cancelederror())
                return request

            task = self._tasks.get(handle)
            while True:
                if task is not None and task.add(request):
                    break
                task = _Task(
                    handle=handle,
                    alert_driver=self._alert_driver,
                    resume_service=self._resume_service,
                )
                self._tasks[handle] = task
                self._add_child(task, terminate_me_on_error=self._pedantic)

        return request

    def discard_request(self, request: Request) -> None:
        with self._lock:
            task = self._tasks.get(request.handle)
            if task is None:
                return
            task.discard(request)

    def _terminate(self) -> None:
        pass

    def _run(self) -> None:
        self._terminated.wait()
        self._log_terminate()
