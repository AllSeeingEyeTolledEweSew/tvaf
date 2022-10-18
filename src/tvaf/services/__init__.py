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
from collections.abc import AsyncIterator
import contextlib
import logging
import pathlib
from typing import AsyncContextManager
from typing import Callable
from typing import ContextManager
from typing import Optional

import anyio
import apsw
import dbver
import libtorrent as lt

from tvaf import caches

from .. import config as config_lib
from .. import driver as driver_lib
from .. import plugins
from .. import request as request_lib
from .. import resume as resume_lib
from .. import session as session_lib

_LOG = logging.getLogger(__name__)

CONFIG_PATH = pathlib.Path("config.json")
RESUME_DB_PATH = pathlib.Path("resume.db")

# Design constraints:
# - Loose coupling to whether the app is a singleton
# - Loose coupling to state storage (contextvars etc)
# - Need "before" and "optional" dependencies

Main = Callable[[], AsyncContextManager]
_MAIN_FUNCS: plugins.Funcs[Main] = plugins.Funcs("tvaf.main")
main_fixture = TODO


@contextlib.asynccontextmanager
async def _main_context() -> AsyncIterator:
    async with contextlib.AsyncExitStack() as stack:
        for name, func in sorted(_MAIN_FUNCS.get().items()):
            _LOG.debug("startup: %s", name)
            await stack.enter_async_context(func())
            stack.callback(_LOG.debug, "shutdown: %s", name)
        yield


class _TaskLifespanAdaptor:
    def __init__(self, ctx: AsyncContextManager) -> None:
        self._started = asyncio.get_event_loop().create_future()
        self._shutdown = asyncio.get_event_loop().create_future()
        self._task = asyncio.create_task(self._run())
        self._ctx = ctx

    async def _run(self) -> None:
        async with self._ctx:
            self._started.set_result(None)
            await asyncio.shield(self._shutdown)

    async def wait_started(self) -> None:
        async def wait_on_task() -> None:
            await asyncio.shield(self._task)

        async with anyio.create_task_group() as tasks:
            tasks.start_soon(wait_on_task)
            await asyncio.shield(self._started)
            tasks.cancel_scope.cancel()

    async def aclose(self) -> None:
        self._shutdown.set_result(None)
        await self._task


_lifespan: Optional[_TaskLifespanAdaptor] = None


async def startup() -> None:
    global _lifespan
    assert _lifespan is None
    _lifespan = _TaskLifespanAdaptor(_main_context())
    try:
        await _lifespan.wait_started()
    except BaseException:
        _lifespan = None
        raise


async def shutdown() -> None:
    global _lifespan
    assert _lifespan is not None
    try:
        await _lifespan.aclose()
    finally:
        _lifespan = None


StageConfig = Callable[[config_lib.Config], AsyncContextManager]
_STAGE_CONFIG_FUNCS: plugins.Funcs[StageConfig] = plugins.Funcs(
    "tvaf.services.stage_config"
)
stage_config_plugin = _STAGE_CONFIG_FUNCS.decorator


def stage_config(config: config_lib.Config) -> AsyncContextManager:
    stages = [func for _, func in sorted(_STAGE_CONFIG_FUNCS.get().items())]
    return config_lib.stage_config(config, *stages)


async def set_config(config: config_lib.Config):
    async with stage_config(config):
        _LOG.debug("config: new config staged, will update...")
    _LOG.info("config: updated")


_config: Optional[config_lib.Config] = None


def get_config() -> config_lib.Config:
    assert _config is not None
    return _config


_config_lock = asyncio.Lock()


@stage_config_plugin("00_lock")
def _stage_config_lock(_: config_lib.Config) -> AsyncContextManager:
    return _config_lock


@stage_config_plugin("80_disk")
@contextlib.asynccontextmanager
async def _stage_config_disk(config: config_lib.Config) -> AsyncIterator:
    tmp_path = CONFIG_PATH.with_suffix(".tmp")
    await config.write_to_disk(tmp_path)
    _LOG.debug("config: staged at %s", tmp_path.resolve())
    try:
        yield
        try:
            await asyncio.to_thread(tmp_path.replace, CONFIG_PATH)
            _LOG.info("config: wrote %s", CONFIG_PATH.resolve())
        except OSError:
            _LOG.exception("couldn't write %s", CONFIG_PATH.resolve())
    finally:
        try:
            await asyncio.to_thread(tmp_path.unlink)
        except FileNotFoundError:
            pass
        except OSError:
            _LOG.exception("can't unlink temp file %s", tmp_path.resolve())


@stage_config_plugin("90_global")
@contextlib.asynccontextmanager
async def _stage_config_global(config: config_lib.Config) -> AsyncIterator:
    yield
    global _config
    _config = config


@main_plugin(name="config")
@contextlib.asynccontextmanager
async def _main_config() -> AsyncIterator[config_lib.Config]:
    global _config
    try:
        _config = await config_lib.Config.from_disk(CONFIG_PATH)
    except FileNotFoundError:
        _config = config_lib.Config()
    try:
        yield _config
    finally:
        _config = None


_session_service: Optional[session_lib.SessionService] = None


def _get_session_service() -> session_lib.SessionService:
    assert _session_service is not None
    return _session_service


def get_session() -> lt.session:
    return _get_session_service().session


def use_alert_mask(alert_mask: int) -> ContextManager:
    return _get_session_service().use_alert_mask(alert_mask)


@main_plugin(name="_session_service")
@contextlib.asynccontextmanager
async def _main_session_service(config:config_lib.Config) -> AsyncIterator[session_lib.SessionService]:
    global _session_service
    assert _session_service is None
    _session_service = session_lib.SessionService(config=get_config())
    try:
        yield _session_service
    finally:
        _session_service = None


@main_plugin(name="session")
@contextlib.asynccontextmanager
async def _main_session(_session_service:session_lib.SessionService) -> AsyncIterator[lt.session]:
    yield _session_service.session

@main_plugin(name="use_alert_mask")
@contextlib.asynccontextmanager
async def _main_use_alert_mask(_session_service:session_lib.SessionService) -> AsyncIterator[session_lib.UseAlertMask]:
    yield _session_service.use_alert_mask


@stage_config_plugin("50_session")
def _stage_config_session_service(config: config_lib.Config) -> AsyncContextManager:
    return _get_session_service().stage_config(config)


_alert_driver: Optional[driver_lib.AlertDriver] = None


def _get_alert_driver() -> driver_lib.AlertDriver:
    assert _alert_driver is not None
    return _alert_driver


def iter_alerts(
    alert_mask: int,
    *types: type[lt.alert],
    handle: lt.torrent_handle = None,
) -> AsyncContextManager[AsyncIterator[lt.alert]]:
    return _get_alert_driver().iter_alerts(alert_mask, *types, handle=handle)


@main_plugin(name="_alert_driver")
@contextlib.asynccontextmanager
async def _main_alert_driver(session:lt.session, use_alert_mask:session_lib.UseAlertMask) -> AsyncIterator[driver_lib.AlertDriver]:
    global _alert_driver
    assert _alert_driver is None
    _alert_driver = driver_lib.AlertDriver(
        session=get_session(), use_alert_mask=use_alert_mask
    )
    try:
        async with anyio.create_task_group() as tasks:
            tasks.start_soon(_alert_driver.run)
            yield _alert_driver
            _alert_driver.shutdown()
    finally:
        _alert_driver = None


@main_plugin(name="iter_alerts")
@contextlib.asynccontextmanager
async def _main_iter_alerts(_alert_driver:driver_lib.AlertDriver) -> AsyncIterator[driver_lib.IterAlerts]:
    yield _alert_driver.iter_alerts


def _resume_db_factory() -> apsw.Connection:
    conn = apsw.Connection(str(RESUME_DB_PATH))
    conn.setbusytimeout(120_000)
    return conn


resume_db_pool = dbver.null_pool(_resume_db_factory)

_resume_service: Optional[resume_lib.ResumeService] = None


def _get_resume_service() -> resume_lib.ResumeService:
    assert _resume_service is not None
    return _resume_service


@main_plugin(name="record_resume_data")
@contextlib.asynccontextmanager
async def _main_record_resume_data() -> AsyncIterator:
    global _resume_service
    assert _resume_service is None
    _resume_service = resume_lib.ResumeService(
        session=get_session(), alert_driver=_get_alert_driver(), pool=resume_db_pool
    )
    try:
        _resume_service.start()
        yield
        _resume_service.close()
        await _resume_service.wait_closed()
    finally:
        _resume_service = None


@main_plugin("30_load_resume_data")
@contextlib.asynccontextmanager
async def _main_load_resume_data() -> AsyncIterator:
    await _get_resume_service().load()
    yield


_request_service: Optional[request_lib.RequestService] = None


def _get_request_service() -> request_lib.RequestService:
    assert _request_service is not None
    return _request_service


@main_plugin("40_request")
@contextlib.asynccontextmanager
async def _main_request_service() -> AsyncIterator:
    global _request_service
    assert _request_service is None
    _request_service = request_lib.RequestService(
        session=get_session(), alert_driver=_get_alert_driver()
    )
    try:
        _request_service.start()
        yield
        _request_service.close()
        await _request_service.wait_closed()
    finally:
        _request_service = None


@main_plugin("15_session_active")
@contextlib.asynccontextmanager
async def _main_session_active() -> AsyncIterator:
    yield
    _LOG.info("shutdown: pausing libtorrent session")
    get_session().pause()


@main_plugin("00_caches")
@contextlib.asynccontextmanager
async def _main_caches() -> AsyncIterator:
    yield
    caches.clear_all()
