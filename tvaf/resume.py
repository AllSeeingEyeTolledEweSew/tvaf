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
from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
import math
import os
import pathlib
import re
from typing import Any
from typing import AsyncIterator
from typing import Awaitable
from typing import Callable
from typing import Coroutine
from typing import Dict
from typing import Iterator
from typing import MutableMapping
from typing import Optional
from typing import Union
import warnings
import weakref

import libtorrent as lt

from . import concurrency
from . import driver as driver_lib
from . import ltpy

_LOG = logging.getLogger(__name__)


async def _try_read(path: pathlib.Path) -> Optional[bytes]:
    try:
        return await concurrency.to_thread(path.read_bytes)
    except FileNotFoundError:
        return None
    except OSError:
        _LOG.exception("while reading %s", path)
        return None


async def _try_load_ti(path: pathlib.Path) -> Optional[lt.torrent_info]:
    data = await _try_read(path)
    if data is None:
        return None

    try:
        with ltpy.translate_exceptions():
            return lt.torrent_info(data)
    except ltpy.Error:
        _LOG.exception("while parsing %s", path)
        return None


async def _try_load_atp(path: pathlib.Path) -> Optional[lt.add_torrent_params]:
    data = await _try_read(path)
    if data is None:
        return None

    try:
        with ltpy.translate_exceptions():
            return lt.read_resume_data(data)
    except ltpy.Error:
        _LOG.exception("while parsing %s", path)
        return None


async def iter_resume_data_from_disk(
    dir_path: Union[str, os.PathLike],
) -> AsyncIterator[lt.add_torrent_params]:
    dir_path = pathlib.Path(dir_path)
    if not await concurrency.to_thread(dir_path.is_dir):
        return
    async for path in concurrency.iter_in_thread(dir_path.iterdir(), batch_size=100):
        if path.suffixes != [".resume"]:
            continue
        if not re.match(r"[0-9a-f]{40}", path.stem):
            continue

        atp = await _try_load_atp(path)
        if not atp:
            continue

        if atp.ti is None:
            atp.ti = await _try_load_ti(path.with_suffix(".torrent"))
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
        with contextlib.suppress(FileNotFoundError):
            tmp_path.unlink()
    _LOG.debug("fastresume: wrote %s", path)


def _delete(path: pathlib.Path) -> None:
    with contextlib.suppress(FileNotFoundError):
        path.unlink()
        _LOG.debug("fastresume: deleted %s", path)


class _ChainedCoroutine:
    def __init__(self, coro: Coroutine) -> None:
        self.coro = coro
        self.next: Optional[Awaitable] = None

    async def run(self) -> None:
        await self.coro
        if self.next:
            concurrency.create_task(self.next)

    def schedule_after(self, other: Optional[_ChainedCoroutine]) -> None:
        if other:
            if inspect.getcoroutinestate(other.coro) != inspect.CORO_CLOSED:
                other.next = self.run()
                return
        asyncio.create_task(self.run())


class ResumeService:
    """ResumeService owns resume data management."""

    SAVE_ALL_INTERVAL = math.tan(1.5657)  # ~196
    TIMEOUT = 10

    def __init__(
        self,
        *,
        session: lt.session,
        alert_driver: driver_lib.AlertDriver,
        path: Union[str, os.PathLike],
    ):
        self._session = session
        self._path = pathlib.Path(path)
        self._alert_driver = alert_driver
        self._got_alert = asyncio.Event()

        self._closed = asyncio.get_event_loop().create_future()
        self._task: Optional[asyncio.Task] = None

        # We want to serialize writes/deletes for a given info hash, so keep a
        # weak pointer to an awaitable for the last-queued job. New jobs will
        # await on the old ones before running.
        self._info_hash_to_write_job: MutableMapping[
            lt.sha1_hash, _ChainedCoroutine
        ] = weakref.WeakValueDictionary()
        self._writes = concurrency.RefCount()

    def get_resume_data_path(self, info_hash: lt.sha1_hash) -> pathlib.Path:
        return self._path.joinpath(str(info_hash)).with_suffix(".resume")

    def get_torrent_path(self, info_hash: lt.sha1_hash) -> pathlib.Path:
        return self._path.joinpath(str(info_hash)).with_suffix(".torrent")

    def _schedule_write(
        self,
        info_hash: lt.sha1_hash,
        func: Callable,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        async def write() -> None:
            await concurrency.to_thread(func, *args, **kwargs)
            self._writes.release()

        self._writes.acquire()
        chained = _ChainedCoroutine(write())
        chained.schedule_after(self._info_hash_to_write_job.get(info_hash))
        self._info_hash_to_write_job[info_hash] = chained

    def _maybe_write(
        self,
        handle: lt.torrent_handle,
        *,
        info_section: bytes = None,
        resume_data: Dict[bytes, Any] = None,
        ignore_if_exists=False,
    ) -> None:
        info_hash = handle.info_hash()
        # See comment in _handle_alert.
        if not ltpy.handle_in_session(handle, self._session):
            return

        if info_section is not None:
            path = self.get_torrent_path(info_hash)
            # torrent info never changes, so only write it once
            if not path.is_file():
                with _write_safe_log(path) as tmp_path:
                    # We want to write a proper .torrent file. We can skip the
                    # bdecode/bencode step if we just write bencoded data
                    # directly
                    with tmp_path.open(mode="wb") as fp:
                        fp.write(b"d4:info")
                        fp.write(info_section)
                        fp.write(b"e")

        if resume_data is not None:
            path = self.get_resume_data_path(info_hash)
            if not ignore_if_exists or not path.is_file():
                # Don't include the info section in the resume data, as it
                # accounts for most of the data but never changes
                resume_data.pop(b"info", None)
                with ltpy.translate_exceptions():
                    bencoded = lt.bencode(resume_data)
                with _write_safe_log(path) as tmp_path:
                    tmp_path.write_bytes(bencoded)

    def _delete(self, info_hash: lt.sha1_hash) -> None:
        _delete(self.get_resume_data_path(info_hash))
        _delete(self.get_torrent_path(info_hash))

    async def _handle_alerts(self) -> None:
        with self._alert_driver.iter_alerts(
            lt.alert_category.status | lt.alert_category.storage,
            lt.save_resume_data_alert,
            lt.add_torrent_alert,
            lt.torrent_removed_alert,
            lt.metadata_received_alert,
            lt.file_renamed_alert,
            lt.storage_moved_alert,
            lt.cache_flushed_alert,
            lt.torrent_paused_alert,
            lt.torrent_finished_alert,
        ) as iterator:
            async for alert in iterator:
                with contextlib.suppress(ltpy.InvalidTorrentHandleError):
                    self._handle_alert(alert)

    def _handle_alert(self, alert: lt.alert) -> None:
        self._got_alert.set()
        # NB: torrent_removed_alert may be followed by other alerts for the
        # same handle, and the handle may still be valid. We must avoid writing
        # data for deleted torrents, but we don't persist per-torrent state to
        # check if torrent_removed_alert happened already for a handle.
        # Instead we call find_torrent() in the writer, as this is synchronized
        # with posting add_torrent_alert and torrent_removed_alert.
        # See https://github.com/arvidn/libtorrent/issues/5112
        if isinstance(alert, lt.save_resume_data_alert):
            self._save_atp(alert.params, alert.handle)
        elif isinstance(alert, lt.add_torrent_alert):
            if alert.error.value():
                return
            # NB: If someone calls async_add_torrent() without
            # duplicate_is_error and the torrent exists, we will get an
            # add_torrent_alert with the params they passed, NOT the original
            # or current params.
            self._save_atp(alert.params, alert.handle, ignore_if_exists=True)
        elif isinstance(alert, lt.torrent_removed_alert):
            self._schedule_write(alert.info_hash, self._delete, alert.info_hash)
        elif isinstance(alert, lt.metadata_received_alert):
            handle = alert.handle

            async def save_torrent_file() -> None:
                try:
                    with ltpy.translate_exceptions():
                        # DOES block
                        ti = await concurrency.to_thread(handle.torrent_file)
                except ltpy.InvalidTorrentHandleError:
                    return
                assert ti is not None
                self._schedule_write(
                    ti.info_hash(),
                    self._maybe_write,
                    handle,
                    info_section=ti.info_section(),
                )

            asyncio.create_task(save_torrent_file())
        elif isinstance(
            alert,
            (
                lt.cache_flushed_alert,
                lt.torrent_paused_alert,
                lt.torrent_finished_alert,
                lt.file_renamed_alert,
                lt.storage_moved_alert,
            ),
        ):
            self._safe_save(alert.handle, flags=lt.save_resume_flags_t.only_if_modified)

    def _safe_save(self, handle: lt.torrent_handle, flags: int = None) -> None:
        with contextlib.suppress(ltpy.InvalidTorrentHandleError):
            with ltpy.translate_exceptions():
                if flags is None:
                    # Does not block
                    handle.save_resume_data()
                else:
                    # Does not block
                    handle.save_resume_data(flags=flags)

    def _save_atp(
        self,
        atp: lt.add_torrent_params,
        handle: lt.torrent_handle,
        ignore_if_exists=False,
    ) -> None:
        info_section: Optional[bytes] = None
        if atp.ti is not None:
            with ltpy.translate_exceptions():
                info_section = atp.ti.info_section()

        # NB: The add_torrent_params object is managed with alert memory. We
        # must do write_resume_data() before the next pop_alerts()

        # NB: We remove the info section (b"info") in the writer, as it's
        # handled separately. It would be more efficient to set ti to None and
        # use write_resume_data_buf(), but it turns out this mutation is
        # visible to other alert handlers.
        with ltpy.translate_exceptions():
            bdecoded = lt.write_resume_data(atp)

        self._schedule_write(
            atp.info_hash,
            self._maybe_write,
            handle,
            info_section=info_section,
            resume_data=bdecoded,
            ignore_if_exists=ignore_if_exists,
        )

    async def _periodic_save_all(self) -> None:
        while True:
            await asyncio.sleep(self.SAVE_ALL_INTERVAL)
            await self._save_all_if_modified(flags=0)

    async def _run(self) -> None:
        periodic = asyncio.create_task(self._periodic_save_all())
        alert_handler = asyncio.create_task(self._handle_alerts())

        _LOG.info("ResumeService started")
        await self._closed
        _LOG.info("ResumeService shutting down")

        periodic.cancel()

        # Design notes: We'd like to explicitly wait for all
        # save_resume_data_alerts and all triggering alerts
        # (storage_moved_alert, etc) to be received. That would require
        # tracking many calls like move_storage() across all code, and this may
        # expand to include other calls. I could not find a good approach to do
        # this from python. For now, just wait for events with a timeout

        # move_storage() across filesystems may take a long time, so don't
        # trust a short timeout. We *could* do this by waiting for alerts but
        # maybe we'll use command counts pretty soon
        while True:
            num_moving_storage = await self._num_moving_storage()
            if num_moving_storage == 0:
                break
            _LOG.info(
                "shutdown: waiting for %d torrents to be done moving storage",
                num_moving_storage,
            )
            await asyncio.sleep(1)

        # final save
        await self._save_all_if_modified(flags=lt.save_resume_flags_t.flush_disk_cache)

        _LOG.info("shutdown: waiting for final resume data")
        while True:
            self._got_alert.clear()
            await concurrency.wait_first([self._got_alert.wait(), asyncio.sleep(1)])
            if not self._got_alert.is_set():
                break

        alert_handler.cancel()

        _LOG.debug("shutdown: waiting for resume data write jobs to complete")
        try:
            await asyncio.wait_for(self._writes.wait_zero(), self.TIMEOUT)
        except asyncio.TimeoutError:
            warnings.warn(
                "Timed out waiting for resume data write jobs. This is a bug. "
                "Resume data is probably incomplete"
            )

    def start(self) -> None:
        assert self._task is None
        self._task = asyncio.create_task(self._run())

    def close(self) -> None:
        if not self._closed.done():
            self._closed.set_result(None)

    async def wait_closed(self) -> None:
        assert self._task is not None
        await self._task

    async def _save_all_if_modified(self, *, flags: int) -> None:
        # Loading all handles at once in python could be cumbersome at large
        # scales, but I don't know of a better way to do this right now
        with ltpy.translate_exceptions():
            # DOES block
            handles = await concurrency.to_thread(self._session.get_torrents)
        # Dispatch need_save_resume_data() all at once
        dispatch = [
            (h, concurrency.to_thread(h.need_save_resume_data)) for h in handles
        ]
        # We don't use save_resume_data(flags=only_if_modified), to avoid
        # overloading the alert queue
        for handle, need_save_resume_data in dispatch:
            with contextlib.suppress(ltpy.InvalidTorrentHandleError):
                with ltpy.translate_exceptions():
                    if await need_save_resume_data:
                        handle.save_resume_data(flags=flags)

    async def _num_moving_storage(self) -> int:
        with ltpy.translate_exceptions():
            # DOES block
            handles = await concurrency.to_thread(self._session.get_torrents)
        statuses = await asyncio.gather(
            *[concurrency.to_thread(h.status) for h in handles]
        )
        return sum(status.moving_storage for status in statuses)
