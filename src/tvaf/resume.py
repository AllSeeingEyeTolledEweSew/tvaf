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
import contextlib
import logging
import math
from typing import Awaitable
from typing import Iterator
from typing import Optional
import warnings

import dbver
import libtorrent as lt

from tvaf._internal import resumedb
from tvaf._internal.resumedb import get_version
from tvaf._internal.resumedb import iter_resume_data_from_db
from tvaf._internal.resumedb import upgrade

from . import concurrency
from . import driver as driver_lib
from . import ltpy

__all__ = ["ResumeService", "get_version", "upgrade", "iter_resume_data_from_db"]

_LOG = logging.getLogger(__name__)


class ResumeService:
    """ResumeService owns resume data management."""

    SAVE_ALL_INTERVAL = math.tan(1.5657)  # ~196
    TIMEOUT = 10

    def __init__(
        self,
        *,
        session: lt.session,
        alert_driver: driver_lib.AlertDriver,
        pool: dbver.Pool,
    ):
        self._session = session
        self._pool = pool
        self._writer = resumedb.Writer(pool)
        self._alert_driver = alert_driver
        self._got_alert = asyncio.Event()

        self._closed = concurrency.create_future()
        self._task: Optional[asyncio.Task] = None

    async def load(self) -> None:
        def iter_atps() -> Iterator[lt.add_torrent_params]:
            with dbver.begin_pool(self._pool, dbver.LockMode.DEFERRED) as conn:
                yield from iter_resume_data_from_db(conn)

        async for atp in concurrency.iter_in_thread(iter_atps()):
            # Does not block
            self._session.async_add_torrent(atp)

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

        # NB: since 2.0.1, save_resume_data_alert is synchronized with
        # add_torrent_alert/torrent_removed_alert
        if isinstance(alert, lt.save_resume_data_alert):
            self._add_job_save_atp(alert.params)
        elif isinstance(alert, lt.add_torrent_alert):
            if alert.error.value():
                return
            # NB: If someone calls async_add_torrent() without
            # duplicate_is_error and the torrent exists, we will get an
            # add_torrent_alert with the params they passed, NOT the original
            # or current params.
            self._add_job_save_atp(alert.params, overwrite=False)

            if alert.params.ti is not None:
                self._add_job_save_ti(concurrency.create_future(alert.params.ti))
        elif isinstance(alert, lt.torrent_removed_alert):
            self._writer.add(
                concurrency.create_future(resumedb.Delete(alert.info_hashes))
            )
        elif isinstance(alert, lt.metadata_received_alert):
            # metadata_received_alert is only emitted when we have the complete
            # info section, including all piece layers for a v2 torrent
            handle = alert.handle

            async def get_ti() -> Optional[lt.torrent_info]:
                try:
                    with ltpy.translate_exceptions():
                        # DOES block
                        return await concurrency.to_thread(handle.torrent_file)
                except ltpy.InvalidTorrentHandleError:
                    return None

            self._add_job_save_ti(asyncio.create_task(get_ti()))
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
            with contextlib.suppress(ltpy.InvalidTorrentHandleError):
                with ltpy.translate_exceptions():
                    # Does not block
                    alert.handle.save_resume_data(
                        flags=lt.save_resume_flags_t.only_if_modified
                    )

    def _add_job_save_atp(
        self,
        atp: lt.add_torrent_params,
        overwrite=True,
    ) -> None:
        # NB: The add_torrent_params object is managed with alert memory. We
        # must do write_resume_data() before the next pop_alerts()

        # write_resume_data() will store the info dict if it's set. It makes up the
        # majority of the data and is immutable, so we manage it separately.

        # Common case: we call save_resume_data without save_info_dict, so the info
        # won't be set.
        if atp.ti is None:
            with ltpy.translate_exceptions():
                resume_data = lt.write_resume_data_buf(atp)
        # In other cases, including add_torrent_alert, info will be set
        else:
            # It would be more efficient to set ti to None and call
            # write_resume_data_buf(), but it turns out the mutation is visible to
            # other alert handlers
            with ltpy.translate_exceptions():
                bdecoded = lt.write_resume_data(atp)
            bdecoded.pop(b"info", None)
            with ltpy.translate_exceptions():
                resume_data = lt.bencode(bdecoded)
        self._writer.add(
            concurrency.create_future(
                resumedb.WriteResumeData(
                    info_hashes=atp.info_hashes,
                    resume_data=resume_data,
                    overwrite=overwrite,
                )
            )
        )

    def _add_job_save_ti(self, maybe_ti: Awaitable[Optional[lt.torrent_info]]) -> None:
        async def make_save_info_job() -> Optional[resumedb.WriteInfo]:
            ti = await maybe_ti
            if ti is None:
                return None
            with ltpy.translate_exceptions():
                # Does not block
                info_hashes = ti.info_hashes()
                # Does not block
                info = ti.info_section()
            return resumedb.WriteInfo(info_hashes=info_hashes, info=info)

        self._writer.add(asyncio.create_task(make_save_info_job()))

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
            await asyncio.wait_for(self._writer.close(), self.TIMEOUT)
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
