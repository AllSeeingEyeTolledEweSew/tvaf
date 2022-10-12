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
import collections
from collections.abc import AsyncIterator
from collections.abc import Iterator
import contextlib
import functools
import logging
import math
from typing import Any
from typing import Callable
from typing import cast
from typing import Optional

import anyio
import anyio.abc
import apsw
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


@contextlib.contextmanager
def _translate_and_ignore_removed() -> Iterator:
    with contextlib.suppress(ltpy.InvalidTorrentHandleError):
        with ltpy.translate_exceptions():
            yield


class ResumeService:
    """ResumeService owns resume data management."""

    SAVE_ALL_INTERVAL = math.tan(1.5657)  # ~196

    def __init__(
        self,
        *,
        session: lt.session,
        iter_alerts: driver_lib.IterAlerts,
        pool: dbver.Pool[apsw.Connection],
    ):
        self._session = session
        self._iter_alerts = iter_alerts
        self._pool = pool

        self._queue: resumedb.Queue = asyncio.Queue()
        self._got_alert = asyncio.Event()

    async def load(self) -> None:
        def iter_atps() -> Iterator[lt.add_torrent_params]:
            with dbver.begin_pool(self._pool, dbver.LockMode.DEFERRED) as conn:
                yield from iter_resume_data_from_db(conn)

        async for atp in concurrency.iter_in_thread(iter_atps()):
            # Does not block
            self._session.async_add_torrent(atp)

    async def _handle_status_changes(
        self, background_tasks: anyio.abc.TaskGroup
    ) -> None:
        async with self._iter_alerts(
            lt.alert_category.status,
            lt.save_resume_data_alert,
            lt.add_torrent_alert,
            lt.torrent_removed_alert,
            lt.metadata_received_alert,
        ) as iterator:
            async for alert in iterator:
                self._got_alert.set()
                self._handle_status_alert(alert, background_tasks)

    def _handle_status_alert(
        self, alert: lt.alert, background_tasks: anyio.abc.TaskGroup
    ) -> None:
        # NB: torrent_removed_alert may be followed by other alerts for the
        # same handle, and the handle may still be valid. We must avoid writing
        # data for deleted torrents, but we don't persist per-handle state to
        # check if torrent_removed_alert happened already for a handle.
        # Instead we call find_torrent() in the writer, as this is synchronized
        # with posting add_torrent_alert and torrent_removed_alert.
        # See https://github.com/arvidn/libtorrent/issues/5112

        # NB: since 2.0.1, save_resume_data_alert is synchronized with
        # add_torrent_alert/torrent_removed_alert
        if isinstance(alert, lt.save_resume_data_alert):
            self._add(resumedb.update_resume_data, resumedb.copy(alert.params))
            if alert.params.ti is not None:
                self._add(resumedb.update_info, alert.params.ti)
        elif isinstance(alert, lt.add_torrent_alert):
            if alert.error.value():
                return
            # NB: If someone calls async_add_torrent() without
            # duplicate_is_error and the torrent exists, we will get an
            # add_torrent_alert with the params they passed, NOT the original
            # or current params.
            self._add(
                resumedb.insert_or_ignore_resume_data, resumedb.copy(alert.params)
            )
            if alert.params.ti is not None:
                self._add(resumedb.update_info, alert.params.ti)
        elif isinstance(alert, lt.torrent_removed_alert):
            self._add(resumedb.delete, alert.info_hashes)
        elif isinstance(alert, lt.metadata_received_alert):
            self._metadata_received(alert.handle, background_tasks)

    def _metadata_received(
        self, handle: lt.torrent_handle, background_tasks: anyio.abc.TaskGroup
    ) -> None:
        async def get_ti() -> Optional[lt.torrent_info]:
            # As of 2.0.6, metadata_received_alert may still be posted after
            # torrent_removed_alert. This creates pathological cases like this:
            # - add a hybrid torrent without metadata
            # - remove it
            # - add the same torrent, with only one info-hash (only v1 or only v2)
            # - receive metadata_received_alert for the *first* handle
            # - add the new info hash for our record
            # Further alerts (including torrent_removed_alert) won't match the
            # record, as we key records by the *combination* of hashes.
            if not await asyncio.to_thread(
                ltpy.handle_in_session, handle, self._session
            ):
                return None
            try:
                with ltpy.translate_exceptions():
                    # DOES block
                    ti = await asyncio.to_thread(handle.torrent_file)
            except ltpy.InvalidTorrentHandleError:
                return None
            # metadata_received_alert is only emitted when we have the complete info
            # section, including all piece layers for a v2 torrent, so torrent_file()
            # should always be non-null
            assert ti is not None
            return ti

        async def resolve(job: asyncio.Future[resumedb.Job]) -> None:
            ti = await get_ti()
            if ti is not None:
                job.set_result(
                    functools.partial(resumedb.update_info_hashes_and_info, ti)
                )
            else:
                job.set_result(lambda conn: None)

        job: asyncio.Future[resumedb.Job] = asyncio.get_event_loop().create_future()
        background_tasks.start_soon(resolve, job)
        self._queue.put_nowait(job)

    def _add(self, func: Callable[..., None], *args: Any) -> None:
        job = functools.partial(func, *args)
        self._queue.put_nowait(concurrency.create_future(job))

    async def _handle_save_triggers(self) -> None:
        async with self._iter_alerts(
            lt.alert_category.status | lt.alert_category.storage,
            lt.cache_flushed_alert,
            lt.torrent_paused_alert,
            lt.torrent_resumed_alert,
            lt.torrent_finished_alert,
            lt.file_renamed_alert,
            lt.storage_moved_alert,
        ) as iterator:
            async for alert in iterator:
                self._got_alert.set()
                handle = cast(lt.torrent_alert, alert).handle
                with _translate_and_ignore_removed():
                    handle.save_resume_data(
                        flags=lt.save_resume_flags_t.only_if_modified
                    )

    async def _periodic_save_all(self) -> None:
        while True:
            await asyncio.sleep(self.SAVE_ALL_INTERVAL)
            await self._save_all_if_modified(flags=0)

    @contextlib.asynccontextmanager
    async def record(self) -> AsyncIterator:
        async with anyio.create_task_group() as writer_tasks:
            writer_tasks.start_soon(resumedb.write, self._pool, self._queue)
            async with anyio.create_task_group() as background_tasks:
                async with anyio.create_task_group() as alert_tasks:
                    alert_tasks.start_soon(
                        self._handle_status_changes, background_tasks
                    )
                    alert_tasks.start_soon(self._handle_save_triggers)

                    async with anyio.create_task_group() as periodic_tasks:
                        periodic_tasks.start_soon(self._periodic_save_all)
                        yield
                        periodic_tasks.cancel_scope.cancel()

                    _LOG.debug(
                        "shutdown: waiting for all torrents to be done moving storage"
                    )
                    await self._wait_done_moving_storage()
                    await self._save_all_if_modified(
                        flags=lt.save_resume_flags_t.flush_disk_cache
                    )
                    _LOG.debug("shutdown: waiting for final resume data")
                    await self._wait_all_resume_data_received()
                    alert_tasks.cancel_scope.cancel()
                _LOG.debug("shutdown: waiting for resume data background tasks")
            self._queue.put_nowait(None)
            _LOG.debug("shutdown: waiting for resume data write jobs to complete")

    async def _save_all_if_modified(self, *, flags: int) -> None:
        # Loading all handles at once in python could be cumbersome at large
        # scales, but I don't know of a better way to do this right now
        with ltpy.translate_exceptions():
            # DOES block
            handles = await asyncio.to_thread(self._session.get_torrents)
        # We don't use save_resume_data(flags=only_if_modified), to avoid
        # overloading the alert queue
        handles_needing_save_resume_data: list[lt.torrent_handle] = []

        async def check_one(handle: lt.torrent_handle) -> None:
            with _translate_and_ignore_removed():
                if await asyncio.to_thread(handle.need_save_resume_data):
                    handles_needing_save_resume_data.append(handle)

        async with anyio.create_task_group() as tasks:
            for handle in handles:
                tasks.start_soon(check_one, handle)
        for handle in handles_needing_save_resume_data:
            with _translate_and_ignore_removed():
                handle.save_resume_data(flags=flags)

    async def _wait_done_moving_storage(self) -> None:
        futures: dict[lt.torrent_handle, asyncio.Future] = collections.defaultdict(
            asyncio.get_event_loop().create_future
        )

        async def wait_for_one(handle: lt.torrent_handle) -> None:
            try:
                with ltpy.translate_exceptions():
                    # TODO: use query_name once it's bound
                    status = await asyncio.to_thread(handle.status)
                    name = await asyncio.to_thread(handle.name)
            except ltpy.InvalidTorrentHandleError:
                return
            if not status.moving_storage:
                return
            _LOG.info("shutdown: waiting for storage move to complete: %s", name)
            await futures[handle]
            _LOG.info("shutdown: done waiting: %s", name)

        async with contextlib.AsyncExitStack() as stack:
            iterator = await stack.enter_async_context(
                self._iter_alerts(
                    lt.alert_category.storage | lt.alert_category.status,
                    lt.storage_moved_alert,
                    lt.storage_moved_failed_alert,
                    lt.torrent_removed_alert,
                )
            )

            async def handle_alerts() -> None:
                async for alert in iterator:
                    handle = cast(lt.torrent_alert, alert).handle
                    future = futures[handle]
                    if not future.done():
                        future.set_result(None)

            alert_tasks = await stack.enter_async_context(anyio.create_task_group())
            alert_tasks.start_soon(handle_alerts)
            with ltpy.translate_exceptions():
                handles = await asyncio.to_thread(self._session.get_torrents)
            async with anyio.create_task_group() as wait_tasks:
                for handle in handles:
                    wait_tasks.start_soon(wait_for_one, handle)
            alert_tasks.cancel_scope.cancel()

    async def _wait_all_resume_data_received(self) -> None:
        # Design notes: We'd like to explicitly wait for all
        # save_resume_data_alerts and all triggering alerts
        # (storage_moved_alert, etc) to be received. That would require
        # tracking many calls like move_storage() across all code, and this may
        # expand to include other calls. I could not find a good approach to do
        # this from python. For now, just wait for events with a timeout
        _LOG.info("shutdown: waiting for final resume data")
        done = False
        while not done:
            self._got_alert.clear()
            try:
                async with anyio.fail_after(1):
                    await self._got_alert.wait()
            except TimeoutError:
                done = True
