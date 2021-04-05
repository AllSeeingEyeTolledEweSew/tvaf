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
import contextlib
import enum
import logging
import pathlib
import threading
from typing import Any
from typing import Dict
from typing import Iterable
from typing import Iterator
from typing import Mapping
from typing import MutableMapping
from typing import Optional
from typing import Set
from weakref import WeakValueDictionary

import libtorrent as lt

from tvaf import config as config_lib
from tvaf import driver as driver_lib
from tvaf import ltpy
from tvaf import resume as resume_lib
from tvaf import task as task_lib
from tvaf import types
from tvaf import util
from tvaf import xmemoryview as xmv

_LOG = logging.getLogger(__name__)

DEFAULT_DOWNLOAD_DIR_NAME = "downloads"


class Mode(enum.Enum):

    READ = "read"
    READAHEAD = "readahead"


def _raise_notimplemented() -> None:
    raise NotImplementedError


class Error(Exception):

    pass


class FetchError(Error):

    pass


class CanceledError(Error):

    pass


class TorrentRemovedError(CanceledError):

    pass


class Request:
    def __init__(
        self,
        *,
        info_hash: types.InfoHash,
        start: int,
        stop: int,
        mode: Mode,
        configure_atp: types.ConfigureATP,
    ):
        self.info_hash = info_hash
        self.start = start
        self.stop = stop
        self.mode = mode
        self.configure_atp = configure_atp

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

    def __init__(self):
        self._ti: Optional[lt.torrent_info] = None
        self._handle: Optional[lt.torrent_handle] = None
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
        self._update_priorities()

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
        self._update_priorities()

    def get_ti(self) -> Optional[lt.torrent_info]:
        return self._ti

    def set_ti(self, ti: lt.torrent_info) -> None:
        if self._ti is not None:
            return
        self._ti = ti
        for request in list(self._requests.values()):
            self._index_request(request)
        self._update_priorities()

    def set_handle(self, handle: Optional[lt.torrent_handle]) -> None:
        if handle == self._handle:
            return
        self._handle = handle
        self._apply_priorities()

    def _update_priorities(self) -> None:
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
        if self._handle is None or self._ti is None:
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
        try:
            with ltpy.translate_exceptions():
                self._apply_priorities_inner()
        except ltpy.InvalidTorrentHandleError:
            pass

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
        self.set_handle(None)
        self._exception = exception

    def get_exception(self) -> Optional[BaseException]:
        return self._exception

    def iter_requests(self) -> Iterator[Request]:
        return iter(self._requests.values())

    def has_requests(self) -> bool:
        return bool(self._requests)

    # TODO: pause and resume

    # TODO: baseline priorities

    # TODO: handle checking state

    # TODO: periodically reissue deadlines


class _Cleanup:
    def __init__(
        self,
        *,
        handle: lt.torrent_handle,
        session: lt.session,
        alert_driver: driver_lib.AlertDriver,
    ):
        self._handle = handle
        self._session = session
        self._alert_driver = alert_driver

    def _cleanup_inner(self) -> None:
        # TODO: what should we do in checking state?

        # DOES block
        status = self._handle.status()
        if status.total_done != 0:
            return
        # DOES block
        if any(self._handle.get_piece_priorities()):
            return

        # We have no whole pieces, and none are downloading. Do a graceful
        # pause to drain outstanding block requests
        if status.flags & lt.torrent_flags.paused == 0:
            iterator = self._alert_driver.iter_alerts(
                lt.alert_category.status,
                lt.torrent_paused_alert,
                lt.torrent_removed_alert,
            )
            with iterator:
                # Does not block
                self._handle.pause(flags=lt.torrent_handle.graceful_pause)
                for alert in iterator:
                    if isinstance(alert, lt.torrent_removed_alert):
                        return
                    if isinstance(alert, lt.torrent_paused_alert):
                        break

            status = self._handle.status()
            if status.total_done != 0:
                # We downloaded some pieces due to graceful pause!
                self._handle.resume()
                return

        # Torrent has no data, no pieces prioritized, and all peers are
        # drained. Clear to delete
        self._session.remove_torrent(
            self._handle, option=lt.options_t.delete_files
        )

    def cleanup(self) -> None:
        with ltpy.translate_exceptions():
            self._cleanup_inner()


class _TorrentTask(task_lib.Task):
    def __init__(
        self,
        *,
        info_hash: types.InfoHash,
        alert_driver: driver_lib.AlertDriver,
        resume_service: resume_lib.ResumeService,
        session: lt.session,
        prev_task: task_lib.Task = None,
    ):
        super().__init__(title=f"request handler for {info_hash}")
        self._info_hash = info_hash
        self._alert_driver = alert_driver
        self._resume_service = resume_service
        self._session = session
        self._prev_task = prev_task

        # TODO: fixup typing here
        self._lock: threading.Condition = threading.Condition(  # type: ignore
            threading.RLock()
        )
        self._state = _State()
        self._iterator: Optional[driver_lib.Iterator] = None

    def add(self, *requests: Request) -> bool:
        with self._lock:
            if self._terminated.is_set():
                return False
            self._state.add(*requests)
            self._lock.notify_all()
            return True

    def discard(self, *requests: Request) -> None:
        with self._lock:
            self._state.discard(*requests, exception=CanceledError())
            self._close_if_no_requests_locked()

    def _close_if_no_requests_locked(self) -> None:
        if not self._state.has_requests():
            if self._iterator:
                self._iterator.close()

    def _set_exception(self, exception: BaseException) -> None:
        with self._lock:
            # More helpful exception. Do this here so that external
            # terminations (due to future linking) get translated
            if isinstance(exception, ltpy.InvalidTorrentHandleError):
                exception = TorrentRemovedError()
            super()._set_exception(exception)
            self._state.set_exception(exception)

    def _terminate(self) -> None:
        with self._lock:
            if self._iterator is not None:
                self._iterator.close()
            # Normal termination still terminates requests (but doesn't count
            # as the task canceling abnormally)
            if self._state.get_exception() is None:
                self._state.set_exception(CanceledError())
            self._lock.notify_all()

    def _handle_alert_locked(self, alert: lt.alert) -> None:
        if isinstance(alert, lt.read_piece_alert):
            exc = ltpy.exception_from_error_code(alert.error)
            self._state.on_read_piece(alert.piece, alert.buffer, exc)
        elif isinstance(alert, lt.torrent_removed_alert):
            raise TorrentRemovedError()
        elif isinstance(alert, lt.save_resume_data_alert):
            if alert.params.ti is not None:
                self._state.set_ti(alert.params.ti)
        elif isinstance(alert, lt.torrent_error_alert):
            # These are mostly disk errors
            exc = ltpy.exception_from_error_code(alert.error)
            if exc is not None:
                raise exc
        elif isinstance(alert, lt.metadata_received_alert):
            self._resume_service.save(
                alert.handle, flags=lt.torrent_handle.save_info_dict
            )

    def _handle_alerts_until_no_requests(
        self, handle: lt.torrent_handle
    ) -> None:
        with self._lock:
            if not self._state.has_requests():
                return
            _LOG.debug("we have active requests, watching alerts")
            self._iterator = self._alert_driver.iter_alerts(
                lt.alert_category.status,
                lt.read_piece_alert,
                lt.torrent_removed_alert,
                lt.save_resume_data_alert,
                lt.torrent_error_alert,
                lt.metadata_received_alert,
                handle=handle,
            )

        with self._iterator:
            with self._lock:
                # Do this after iterator creation, as it generates alerts
                self._state.set_handle(handle)
                if self._state.get_ti() is None:
                    self._resume_service.save(
                        handle, flags=lt.torrent_handle.save_info_dict
                    )

            for alert in self._iterator:
                with self._lock:
                    self._handle_alert_locked(alert)
                    self._close_if_no_requests_locked()

    def _run_with_handle(self, handle: lt.torrent_handle) -> None:
        with ltpy.translate_exceptions():
            # Does not block
            handle.clear_error()
            # DOES block
            ti = handle.torrent_file()

        with self._lock:
            if ti is not None:
                self._state.set_ti(ti)

        # Loop until we have no requests for 60s, or are terminated
        while not self._terminated.is_set():
            self._handle_alerts_until_no_requests(handle)

            _LOG.debug("no more requests, waiting to cleanup")
            # Instead of switching between an active iterator and a condition
            # wait, it would be nicer to "select" on the iterator and a timeout
            with self._lock:

                def wakeup() -> bool:
                    return (
                        self._terminated.is_set() or self._state.has_requests()
                    )

                if not self._lock.wait_for(wakeup, timeout=60):
                    self.terminate()

        _LOG.debug("cleaning up")
        # We won't run cleanup if we get an exception. This is probably for the
        # best
        cleanup = _Cleanup(
            handle=handle,
            session=self._session,
            alert_driver=self._alert_driver,
        )
        cleanup.cleanup()

    def _run(self) -> None:
        # The previous task must have been terminated, but it may still be
        # touching the handle. Wait for it to finish.
        if self._prev_task is not None:
            self._prev_task.join()
            self._prev_task = None

        with ltpy.translate_exceptions():
            info_hash = lt.sha1_hash(bytes.fromhex(self._info_hash))
            # DOES block
            handle = self._session.find_torrent(info_hash)

        if not handle.is_valid():
            with self._lock:
                if not self._state.has_requests():
                    self.terminate()
                    return
                # Should we use different logic?
                request = next(self._state.iter_requests())

            atp = lt.add_torrent_params()
            atp.info_hash = info_hash
            try:
                request.configure_atp(atp)
            except Exception as exc:
                raise FetchError() from exc

            atp.flags &= ~(
                lt.torrent_flags.paused | lt.torrent_flags.duplicate_is_error
            )
            # TODO: how do we support this with magnet links?
            assert atp.ti is not None
            # atp.file_priorities = [0] * atp.ti.num_files()
            atp.piece_priorities = [0] * atp.ti.num_pieces()

            # If we fail, should we retry with a different request?
            with ltpy.translate_exceptions():
                # DOES block
                handle = self._session.add_torrent(atp)

            # The "victim" request may have been removed while we were
            # fetching and adding. We could check and loop

        self._run_with_handle(handle)


class RequestService(task_lib.Task, config_lib.HasConfig):
    def __init__(
        self,
        *,
        config: config_lib.Config,
        alert_driver: driver_lib.AlertDriver,
        resume_service: resume_lib.ResumeService,
        session: lt.session,
        pedantic=False,
    ):
        super().__init__(title="RequestService", thread_name="request")
        self._alert_driver = alert_driver
        self._resume_service = resume_service
        self._session = session
        self._pedantic = pedantic

        self._lock = threading.RLock()
        # As of 3.8, WeakValueDictionary is unsubscriptable
        self._torrent_tasks = (
            WeakValueDictionary()
        )  # type: WeakValueDictionary[types.InfoHash, _TorrentTask]

        self._atp_settings: Mapping[str, Any] = {}

        self.set_config(config)

    def add_request(
        self,
        *,
        info_hash: types.InfoHash,
        start: int,
        stop: int,
        mode: Mode,
        configure_atp: types.ConfigureATP,
    ) -> Request:
        def _configure_atp_with_settings(atp: lt.add_torrent_params) -> None:
            configure_atp(atp)
            self.configure_atp(atp)

        request = Request(
            info_hash=info_hash,
            start=start,
            stop=stop,
            mode=mode,
            configure_atp=_configure_atp_with_settings,
        )

        with self._lock:
            if self._terminated.is_set():
                request.set_exception(
                    CanceledError("RequestService terminated")
                )
                return request

            task = self._torrent_tasks.get(info_hash)
            while True:
                if task is not None and task.add(request):
                    break
                task = _TorrentTask(
                    info_hash=info_hash,
                    alert_driver=self._alert_driver,
                    resume_service=self._resume_service,
                    session=self._session,
                    prev_task=task,
                )
                self._torrent_tasks[info_hash] = task
                self._add_child(task, terminate_me_on_error=self._pedantic)

        return request

    def discard_request(self, request: Request) -> None:
        with self._lock:
            task = self._torrent_tasks.get(request.info_hash)
            if task is None:
                return
            task.discard(request)

    def _terminate(self) -> None:
        pass

    def _run(self) -> None:
        self._terminated.wait()
        self._log_terminate()

    @contextlib.contextmanager
    def stage_config(self, config: config_lib.Config) -> Iterator[None]:
        config.setdefault(
            "torrent_default_save_path",
            str(pathlib.Path(DEFAULT_DOWNLOAD_DIR_NAME).resolve()),
        )

        atp_settings: MutableMapping[str, Any] = {}

        save_path = pathlib.Path(
            config.require_str("torrent_default_save_path")
        )
        try:
            # Raises RuntimeError on symlink loops
            save_path = save_path.resolve()
        except RuntimeError as exc:
            raise config_lib.InvalidConfigError(str(exc)) from exc

        atp_settings["save_path"] = str(save_path)

        name_to_flag = {
            "apply_ip_filter": lt.torrent_flags.apply_ip_filter,
        }

        for name, flag in name_to_flag.items():
            key = f"torrent_default_flags_{name}"
            value = config.get_bool(key)
            if value is None:
                continue
            atp_settings.setdefault("flags", lt.torrent_flags.default_flags)
            if value:
                atp_settings["flags"] |= flag
            else:
                atp_settings["flags"] &= ~flag

        maybe_name = config.get_str("torrent_default_storage_mode")
        if maybe_name is not None:
            full_name = f"storage_mode_{maybe_name}"
            mode = lt.storage_mode_t.names.get(full_name)
            if mode is None:
                raise config_lib.InvalidConfigError(
                    f"invalid storage mode {maybe_name}"
                )
            atp_settings["storage_mode"] = mode

        with self._lock:
            yield
            self._atp_settings = atp_settings

    def configure_atp(self, atp: lt.add_torrent_params) -> None:
        atp_settings = self._atp_settings
        for key, value in atp_settings.items():
            setattr(atp, key, value)
