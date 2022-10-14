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
import pathlib
import random

import anyio
import libtorrent as lt
import pytest

from tests import conftest
from tvaf import config as config_lib
from tvaf import driver as driver_lib
from tvaf import ltpy
from tvaf import session as session_lib
from tvaf.services import util as services_util


@pytest.fixture
def ti() -> lt.torrent_info:
    fs = lt.file_storage()
    fs.add_file("test.txt", 1024)
    ct = lt.create_torrent(fs)
    ct.set_hash(0, random.randbytes(20))
    return lt.torrent_info(ct.generate())


@pytest.fixture
def atp(ti: lt.torrent_info, tmp_path: pathlib.Path) -> lt.add_torrent_params:
    local_atp = lt.add_torrent_params()
    local_atp.save_path = str(tmp_path)
    local_atp.info_hashes = ti.info_hashes()
    return local_atp


@pytest.fixture
def session_service(config: config_lib.Config) -> session_lib.SessionService:
    return session_lib.SessionService(config=config)


@pytest.fixture
def use_alert_mask(
    session_service: session_lib.SessionService,
) -> session_lib.UseAlertMask:
    return session_service.use_alert_mask


@pytest.fixture
def session(session_service: session_lib.SessionService) -> lt.session:
    return session_service.session


@pytest.fixture
def handle(atp: lt.add_torrent_params, session: lt.session) -> lt.torrent_handle:
    return session.add_torrent(atp)


@pytest.fixture
async def iter_alerts(
    use_alert_mask: session_lib.UseAlertMask,
    session: lt.session,
) -> AsyncIterator[driver_lib.IterAlerts]:
    alert_driver = driver_lib.AlertDriver(
        use_alert_mask=use_alert_mask, session=session
    )
    task = asyncio.create_task(alert_driver.run())
    yield alert_driver.iter_alerts
    alert_driver.shutdown()
    await task


@conftest.timeout(60)
async def test_set_before_start(
    iter_alerts: driver_lib.IterAlerts, handle: lt.torrent_handle, ti: lt.torrent_info
) -> None:
    handle.set_metadata(ti.info_section())
    got_ti = await services_util.get_torrent_info(
        handle=handle, iter_alerts=iter_alerts
    )
    assert got_ti.info_section() == ti.info_section()


@conftest.timeout(60)
async def test_set_after_start(
    iter_alerts: driver_lib.IterAlerts, handle: lt.torrent_handle, ti: lt.torrent_info
) -> None:
    result: asyncio.Future[lt.torrent_info] = asyncio.get_event_loop().create_future()
    waiting_for_alert = asyncio.get_event_loop().create_future()

    async def get() -> None:
        result.set_result(
            await services_util.get_torrent_info(
                handle=handle,
                iter_alerts=iter_alerts,
                _waiting_for_alert=waiting_for_alert,
            )
        )

    async with anyio.create_task_group() as tasks:
        tasks.start_soon(get)
        await waiting_for_alert
        handle.set_metadata(ti.info_section())
    got_ti = await result
    assert got_ti.info_section() == ti.info_section()


@conftest.timeout(60)
async def test_remove_before_start(
    iter_alerts: driver_lib.IterAlerts, handle: lt.torrent_handle, session: lt.session
) -> None:
    session.remove_torrent(handle)
    while handle.is_valid():
        pass
    with pytest.raises(ltpy.InvalidTorrentHandleError):
        await services_util.get_torrent_info(handle=handle, iter_alerts=iter_alerts)


@conftest.timeout(60)
async def test_remove_after_start(
    iter_alerts: driver_lib.IterAlerts, handle: lt.torrent_handle, session: lt.session
) -> None:
    waiting_for_alert = asyncio.get_event_loop().create_future()

    async def get() -> None:
        await services_util.get_torrent_info(
            handle=handle, iter_alerts=iter_alerts, _waiting_for_alert=waiting_for_alert
        )

    with pytest.raises(ltpy.InvalidTorrentHandleError):
        async with anyio.create_task_group() as tasks:
            tasks.start_soon(get)
            await waiting_for_alert
            session.remove_torrent(handle)
