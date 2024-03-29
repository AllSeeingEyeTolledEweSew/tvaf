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
import tempfile
import unittest

import anyio
import libtorrent as lt

from tvaf import driver as driver_lib

from . import lib
from . import tdummy


class DummyException(Exception):
    pass


# NB: We'd like to test that iterators don't hold any unintended references to
# alerts, but this is hard to test because exceptions refer to stack frames
# which refer to alerts in many cases, including StopIteration.


class IterAlertsTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        session_service = lib.create_isolated_session_service()
        self.session = session_service.session
        self.driver = driver_lib.AlertDriver(
            session=self.session, use_alert_mask=session_service.use_alert_mask
        )
        self.iter_alerts: driver_lib.IterAlerts = self.driver.iter_alerts
        self.task = asyncio.create_task(self.driver.run())
        self.tempdir = tempfile.TemporaryDirectory()
        self.torrent = tdummy.DEFAULT
        self.atp = self.torrent.atp()
        self.atp.save_path = self.tempdir.name

    async def asyncTearDown(self) -> None:
        self.driver.shutdown()
        with anyio.fail_after(60):
            await self.task
        self.tempdir.cleanup()

    async def test_see_alert(self) -> None:
        async with self.iter_alerts(
            lt.alert_category.status, lt.add_torrent_alert
        ) as iterator:
            self.session.async_add_torrent(self.atp)

            alert = await asyncio.wait_for(iterator.__anext__(), 60)
            self.assertIsInstance(alert, lt.add_torrent_alert)

    async def test_filter_by_type(self) -> None:
        async with self.iter_alerts(
            lt.alert_category.status,
            lt.add_torrent_alert,
            lt.torrent_removed_alert,
        ) as iterator:
            handle = self.session.add_torrent(self.atp)
            # should fire state_changed_alert, but we should *not* see it
            await asyncio.wait_for(lib.wait_done_checking_or_error(handle), 60)
            self.session.remove_torrent(handle)

            alert = await asyncio.wait_for(iterator.__anext__(), 60)
            self.assertIsInstance(alert, lt.add_torrent_alert)
            alert = await asyncio.wait_for(iterator.__anext__(), 60)
            self.assertIsInstance(alert, lt.torrent_removed_alert)

    async def test_unfiltered(self) -> None:
        async with self.iter_alerts(
            lt.alert_category.status,
        ) as iterator:
            self.session.add_torrent(self.atp)

            alert = await asyncio.wait_for(iterator.__anext__(), 60)
            # The alert order changed subtly in
            # https://github.com/arvidn/libtorrent/pull/6897
            self.assertIsInstance(alert, (lt.add_torrent_alert, lt.torrent_added_alert))

    async def test_filter_by_handle(self) -> None:
        other_torrent = tdummy.Torrent.single_file(
            piece_length=16384, name=b"other.txt", length=16384 * 9 + 1000
        )
        other_atp = other_torrent.atp()
        other_atp.save_path = self.tempdir.name
        handle = self.session.add_torrent(self.atp)
        other_handle = self.session.add_torrent(other_atp)

        async with self.iter_alerts(
            lt.alert_category.status,
            lt.torrent_removed_alert,
            handle=handle,
        ) as iterator:
            self.session.remove_torrent(other_handle)
            self.session.remove_torrent(handle)

            alert = await asyncio.wait_for(iterator.__anext__(), 60)
            assert isinstance(alert, lt.torrent_removed_alert)
            self.assertEqual(alert.handle, handle)

    async def test_alert_mask(self) -> None:
        def alerts_enabled() -> bool:
            return bool(
                self.session.get_settings()["alert_mask"] & lt.alert_category.status
            )

        self.assertFalse(alerts_enabled())
        async with self.iter_alerts(lt.alert_category.status) as _:
            self.assertTrue(alerts_enabled())
        self.assertFalse(alerts_enabled())

    async def test_exception(self) -> None:
        with self.assertRaises(DummyException):
            async with self.iter_alerts(lt.alert_category.status) as _:
                raise DummyException()

    async def test_alert_mask_with_exception(self) -> None:
        def alerts_enabled() -> bool:
            return bool(
                self.session.get_settings()["alert_mask"] & lt.alert_category.status
            )

        self.assertFalse(alerts_enabled())
        try:
            async with self.iter_alerts(lt.alert_category.status) as _:
                self.assertTrue(alerts_enabled())
                raise DummyException()
        except DummyException:
            pass
        self.assertFalse(alerts_enabled())

    async def test_cancel_iterator(self) -> None:
        checkpoint = asyncio.Event()

        async def iter_task() -> None:
            async with self.iter_alerts(lt.alert_category.status) as iterator:
                checkpoint.set()
                async for _ in iterator:
                    pass

        task = asyncio.create_task(iter_task())
        await asyncio.wait_for(checkpoint.wait(), 60)
        task.cancel()
