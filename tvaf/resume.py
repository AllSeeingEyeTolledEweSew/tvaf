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

import concurrent.futures
import contextlib
import logging
import math
import os
import pathlib
import re
import threading
from typing import Callable
from typing import cast
from typing import Iterator
from typing import Optional
from typing import Union
import warnings

import libtorrent as lt

from tvaf import driver as driver_lib
from tvaf import ltpy
from tvaf import task as task_lib

_LOG = logging.getLogger(__name__)

SAVE_ALL_INTERVAL = math.tan(1.5657)  # ~196


class _Underflow(Exception):

    pass


class _Counter:
    def __init__(self):
        self._condition = threading.Condition()
        self._value: int = 0

    def inc(self, delta: int) -> int:
        with self._condition:
            self._value += delta
            if self._value == 0:
                self._condition.notify_all()
            if self._value < 0:
                self._value = 0
                raise _Underflow()
            return self._value

    def wait_zero(self, timeout: float = None) -> bool:
        with self._condition:
            return bool(
                self._condition.wait_for(
                    lambda: self._value == 0, timeout=timeout
                )
            )


def _try_read(path: pathlib.Path) -> Optional[bytes]:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError:
        _LOG.exception("while reading %s", path)
        return None


def _try_load_ti(path: pathlib.Path) -> Optional[lt.torrent_info]:
    data = _try_read(path)
    if data is None:
        return None

    try:
        with ltpy.translate_exceptions():
            return lt.torrent_info(lt.bdecode(data))
    except ltpy.Error:
        _LOG.exception("while parsing %s", path)
        return None


def _try_load_atp(path: pathlib.Path) -> Optional[lt.add_torrent_params]:
    data = _try_read(path)
    if data is None:
        return None

    try:
        with ltpy.translate_exceptions():
            return lt.read_resume_data(data)
    except ltpy.Error:
        _LOG.exception("while parsing %s", path)
        return None


def iter_resume_data_from_disk(
    dir_path: Union[str, os.PathLike],
) -> Iterator[lt.add_torrent_params]:
    dir_path = pathlib.Path(dir_path)
    if not dir_path.is_dir():
        return
    for path in dir_path.iterdir():
        if path.suffixes != [".resume"]:
            continue
        if not re.match(r"[0-9a-f]{40}", path.stem):
            continue

        atp = _try_load_atp(path)
        if not atp:
            continue

        if atp.ti is None:
            atp.ti = _try_load_ti(path.with_suffix(".torrent"))
        yield atp


@contextlib.contextmanager
def _write_safe_log(path: pathlib.Path) -> Iterator[pathlib.Path]:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    try:
        yield tmp_path
        # Atomic on Linux and Windows, apparently
        tmp_path.replace(path)
    finally:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
    _LOG.debug("wrote: %s", path)


def _delete(path: pathlib.Path) -> None:
    try:
        path.unlink()
        _LOG.debug("deleted: %s", path)
    except FileNotFoundError:
        pass


# NB: If remove_torrent() is immediately followed by save_resume_data(), as
# both calls are asynchronous, it's possible to schedule both before either one
# runs, which results in torrent_removed_alert followed by
# save_resume_data_alert. The handle will be invalid and the params data is
# meaningless. This is actually useful to us: each successful
# save_resume_data() yields exactly one save_resume_data[_failed]_alert.


class _ReceiverTask(task_lib.Task):
    def __init__(
        self,
        *,
        counter: _Counter,
        resume_service: "ResumeService",
        alert_driver: driver_lib.AlertDriver,
        session: lt.session,
        pedantic=False
    ):
        super().__init__(
            title="fastresume data receiver", thread_name="fastresume.receiver"
        )
        self._counter = counter
        self._resume_service = resume_service
        self._session = session
        # Single thread so we synchronize writes/deletes for the same infohash
        # TODO: do something with more throughput
        self._io_executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1
        )
        self._check_executor = concurrent.futures.ThreadPoolExecutor()
        # We handle metadata_received_alert so we're sure to get it at shutdown
        self._iterator = alert_driver.iter_alerts(
            lt.alert_category.status,
            lt.save_resume_data_alert,
            lt.save_resume_data_failed_alert,
            lt.torrent_removed_alert,
            lt.add_torrent_alert,
            lt.metadata_received_alert,
        )
        self._pedantic = pedantic

    def _terminate(self) -> None:
        self._iterator.close()

    def _io_submit(self, func: Callable, *args, **kwargs) -> None:
        future = self._io_executor.submit(func, *args, **kwargs)
        task_lib.log_future_exceptions(future, "in io task")
        if self._pedantic:
            task_lib.terminate_task_on_future_fail(self, future)

    def _write_atp(
        self,
        check: concurrent.futures.Future,
        info_hash: lt.sha1_hash,
        data: bytes,
    ) -> None:
        if not check.result():
            return
        path = self._resume_service.get_resume_data_path(info_hash)
        with _write_safe_log(path) as tmp_path:
            tmp_path.write_bytes(data)

    def _write_ti(
        self,
        check: Optional[concurrent.futures.Future],
        info_hash: lt.sha1_hash,
        metadata: bytes,
    ) -> None:
        if check is not None and not check.result():
            return
        path = self._resume_service.get_torrent_path(info_hash)
        with _write_safe_log(path) as tmp_path:
            # Metadata is the bencoded infodict itself. We want to write a
            # proper .torrent file. We can skip the bdecode/bencode step if we
            # just write bencoded data directly
            with tmp_path.open(mode="wb") as fp:
                fp.write(b"d4:info")
                fp.write(metadata)
                fp.write(b"e")

    def _dec(self) -> None:
        try:
            self._counter.inc(-1)
        except _Underflow:
            warnings.warn(
                "ResumeService received more save_resume_data[_failed]_alerts "
                "than save_resume_data() calls we made. Either someone called "
                "save_resume_data() outside of ResumeService, or there's a "
                "bug in ResumeService"
            )
            if self._pedantic:
                raise

    def _handle_alert(self, alert: lt.alert) -> None:
        if isinstance(alert, lt.save_resume_data_alert):
            atp = alert.params
            handle = alert.handle
            info_hash = handle.info_hash()

            # NB: when save_resume_data_alert follows torrent_removed_alert,
            # the handle may still be alive when we receive the alert
            # (handle.is_valid() is True). If we persist data in this case,
            # and later load it, the user will see a zombie torrent they
            # thought they removed.

            # The list of active torrents in the session is synchronized with
            # add_torrent_alert and torrent_removed_alert, so find_torrent()
            # will never return a handle after torrent_removed_alert was
            # posted. See https://github.com/arvidn/libtorrent/issues/5112
            check = self._check_executor.submit(
                ltpy.handle_in_session, handle, self._session
            )

            # Unconditionally submit to our IO queue, so when we terminate we
            # can wait for it to drain
            if atp.ti is not None:
                with ltpy.translate_exceptions():
                    metadata = atp.ti.metadata()
                self._io_submit(self._write_ti, check, atp.info_hash, metadata)

            # The add_torrent_params object is managed with alert memory. We
            # must do write_resume_data() before the next pop_alerts().
            # It would be more efficient to set ti to None and use
            # write_resume_data_buf(), but other alert handlers would see the
            # mutation
            with ltpy.translate_exceptions():
                bdict = lt.write_resume_data(atp)
                bdict.pop(b"info", None)
                data = lt.bencode(bdict)
            self._io_submit(self._write_atp, check, atp.info_hash, data)
            self._dec()
        elif isinstance(alert, lt.save_resume_data_failed_alert):
            self._dec()
        elif isinstance(alert, lt.add_torrent_alert):
            if alert.error.value():
                return
            # NB: If someone calls async_add_torrent() without
            # duplicate_is_error and the torrent exists, we will get an
            # add_torrent_alert with the params they passed, NOT the original
            # or current params
            atp = alert.params
            if atp.ti is None:
                return
            with ltpy.translate_exceptions():
                metadata = atp.ti.metadata()
            self._io_submit(self._write_ti, None, atp.info_hash, metadata)
        elif isinstance(alert, lt.torrent_removed_alert):
            info_hash = alert.info_hash
            self._io_submit(
                _delete, self._resume_service.get_resume_data_path(info_hash)
            )
            self._io_submit(
                _delete, self._resume_service.get_torrent_path(info_hash)
            )
        elif isinstance(alert, lt.metadata_received_alert):
            self._resume_service.save(
                alert.handle, flags=lt.torrent_handle.save_info_dict
            )

    def _run(self) -> None:
        with self._iterator:
            for alert in self._iterator:
                self._handle_alert(alert)

        self._log_terminate()
        _LOG.debug("waiting for fastresume data to be written to disk")
        self._io_executor.shutdown()


class _TriggerTask(task_lib.Task):
    def __init__(
        self,
        *,
        resume_service: "ResumeService",
        alert_driver: driver_lib.AlertDriver
    ):
        super().__init__(
            title="fastresume save trigger", thread_name="fastresume.trigger"
        )
        self._resume_service = resume_service
        self._iterator = alert_driver.iter_alerts(
            lt.alert_category.storage | lt.alert_category.status,
            lt.file_renamed_alert,
            lt.torrent_paused_alert,
            lt.torrent_finished_alert,
            lt.storage_moved_alert,
            lt.cache_flushed_alert,
        )

    def _terminate(self) -> None:
        self._iterator.close()

    def _run(self) -> None:
        with self._iterator:
            for alert in self._iterator:
                torrent_alert = cast(lt.torrent_alert, alert)
                self._resume_service.save(
                    torrent_alert.handle,
                    flags=lt.torrent_handle.only_if_modified,
                )


class _PeriodicTask(task_lib.Task):
    def __init__(self, resume_service: "ResumeService"):
        super().__init__(
            title="fastresume periodic save", thread_name="fastresume.periodic"
        )
        self._resume_service = resume_service

    def _terminate(self) -> None:
        pass

    def _run(self) -> None:
        while not self._terminated.wait(SAVE_ALL_INTERVAL):
            self._resume_service.save_all(
                flags=lt.torrent_handle.only_if_modified
            )


class ResumeService(task_lib.Task):
    """ResumeService owns resume data management."""

    def __init__(
        self,
        *,
        session: lt.session,
        alert_driver: driver_lib.AlertDriver,
        path: Union[str, os.PathLike],
        pedantic=False
    ):
        super().__init__(title="ResumeService", thread_name="resume")
        self._counter = _Counter()
        self._session = session
        self._path = pathlib.Path(path)

        self._receiver_task = _ReceiverTask(
            resume_service=self,
            alert_driver=alert_driver,
            counter=self._counter,
            session=session,
            pedantic=pedantic,
        )
        self._trigger_task = _TriggerTask(
            resume_service=self, alert_driver=alert_driver
        )
        self._periodic_task = _PeriodicTask(resume_service=self)

        self._add_child(self._receiver_task, start=False)
        self._add_child(self._trigger_task, start=False)
        self._add_child(self._periodic_task, start=False)

    def get_resume_data_path(self, info_hash: lt.sha1_hash) -> pathlib.Path:
        return self._path.joinpath(str(info_hash)).with_suffix(".resume")

    def get_torrent_path(self, info_hash: lt.sha1_hash) -> pathlib.Path:
        return self._path.joinpath(str(info_hash)).with_suffix(".torrent")

    def _terminate(self) -> None:
        pass

    def _run(self) -> None:
        self._receiver_task.start()
        self._trigger_task.start()
        self._periodic_task.start()

        # Main wait
        self._terminated.wait()

        self._log_terminate()

        # _TriggerTask may not have processed all alerts, but we don't care
        # because we're calling save_all()
        self._trigger_task.terminate()
        self._periodic_task.terminate()
        self._trigger_task.join()
        self._periodic_task.join()

        self.save_all(
            flags=lt.torrent_handle.only_if_modified
            | lt.torrent_handle.flush_disk_cache
        )

        # At this point, no more save()s will be issued
        _LOG.debug("waiting for final fastresume data")
        if not self._counter.wait_zero(timeout=15):
            _LOG.error(
                "received less fastresume data than we expected. this is a "
                "bug, and fastresume data may be incomplete"
            )

        self._receiver_task.terminate()
        self._receiver_task.join()

    def save(self, handle: lt.torrent_handle, flags: int = 0) -> None:
        try:
            with ltpy.translate_exceptions():
                # Does not block
                handle.save_resume_data(flags=flags)
        except ltpy.InvalidTorrentHandleError:
            pass
        else:
            self._counter.inc(1)

    def save_all(self, flags: int = 0) -> None:
        # Loading all handles at once in python could be cumbersome at large
        # scales, but I don't know of a better way to do this right now
        with ltpy.translate_exceptions():
            # DOES block
            handles = self._session.get_torrents()
        _LOG.debug("saving fastresume data for %d torrents", len(handles))
        for handle in handles:
            self.save(handle, flags=flags)
