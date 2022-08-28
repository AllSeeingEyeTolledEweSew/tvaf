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
from collections.abc import Awaitable
from collections.abc import Coroutine
import contextlib
import logging
import pathlib
from typing import Any
from typing import AsyncContextManager
from typing import Callable
from typing import Optional

import apsw
import dbver
import libtorrent as lt

from tvaf import caches
from tvaf._internal import main

from .. import config as config_lib
from .. import driver as driver_lib
from .. import plugins
from .. import request as request_lib
from .. import resume as resume_lib
from .. import session as session_lib

_LOG = logging.getLogger(__name__)

CONFIG_PATH = pathlib.Path("config.json")
RESUME_DB_PATH = pathlib.Path("resume.db")


Startup = Callable[[], Awaitable]
_STARTUP_FUNCS: plugins.Funcs[Startup] = plugins.Funcs("tvaf.services.startup")
startup_plugin = _STARTUP_FUNCS.decorator


async def do_startup() -> None:
    for _, func in sorted(_STARTUP_FUNCS.get().items()):
        await func()


Shutdown = Callable[[], Awaitable]
_SHUTDOWN_FUNCS: plugins.Funcs[Shutdown] = plugins.Funcs("tvaf.services.shutdown")
shutdown_plugin = _SHUTDOWN_FUNCS.decorator


async def do_shutdown() -> None:
    for _, func in sorted(_SHUTDOWN_FUNCS.get().items()):
        await func()


_main: Optional[main.MainTaskLifespanAdaptor] = None


async def startup() -> None:
    global _main
    assert _main is None
    try:
        _main = main.MainTaskLifespanAdaptor(do_startup, do_shutdown)
        await _main.startup()
    except BaseException:
        _main = None
        raise


async def shutdown() -> None:
    global _main
    assert _main is not None
    try:
        await _main.shutdown()
    finally:
        _main = None


def start_soon_from_main(
    func: Callable[..., Coroutine[Any, Any, Any]],
    *args: Any,
    name: str = None,
) -> None:
    assert _main is not None
    _main.start_soon(func, *args, name=name)


def cancel_main(msg: str = None) -> None:
    global _main
    try:
        if _main is not None:
            _main.cancel(msg=msg)
    finally:
        _main = None


StageConfig = Callable[[config_lib.Config], AsyncContextManager]
_STAGE_CONFIG_FUNCS: plugins.Funcs[StageConfig] = plugins.Funcs(
    "tvaf.services.stage_config"
)
stage_config_plugin = _STAGE_CONFIG_FUNCS.decorator


def stage_config(config: config_lib.Config) -> AsyncContextManager[None]:
    stages = [func for _, func in sorted(_STAGE_CONFIG_FUNCS.get().items())]
    return config_lib.stage_config(config, *stages)


async def set_config(config: config_lib.Config):
    async with stage_config(config):
        _LOG.debug("config: new config staged, will update...")
    _LOG.info("config: updated")


_process_locked = False


@caches.asingleton()
async def get_config() -> config_lib.Config:
    try:
        return await config_lib.Config.from_disk(CONFIG_PATH)
    except FileNotFoundError:
        return config_lib.Config()


@caches.asingleton()
async def get_session_service() -> session_lib.SessionService:
    return session_lib.SessionService(config=await get_config())


@caches.asingleton()
async def get_session() -> lt.session:
    return (await get_session_service()).session


@caches.asingleton()
async def get_alert_driver() -> driver_lib.AlertDriver:
    return driver_lib.AlertDriver(session_service=await get_session_service())


def _resume_db_factory() -> apsw.Connection:
    conn = apsw.Connection(str(RESUME_DB_PATH))
    conn.setbusytimeout(120_000)
    return conn


resume_db_pool = dbver.null_pool(_resume_db_factory)


@caches.asingleton()
async def get_resume_service() -> resume_lib.ResumeService:
    return resume_lib.ResumeService(
        session=await get_session(),
        alert_driver=await get_alert_driver(),
        pool=resume_db_pool,
    )


@caches.asingleton()
async def get_request_service() -> request_lib.RequestService:
    return request_lib.RequestService(
        alert_driver=await get_alert_driver(),
        session=await get_session(),
    )


_config_lock = asyncio.Lock()


@stage_config_plugin("00_lock")
def _stage_config_lock(_: config_lib.Config) -> AsyncContextManager:
    return _config_lock


@stage_config_plugin("80_disk")
@contextlib.asynccontextmanager
async def _stage_config_disk(config: config_lib.Config) -> AsyncIterator[None]:
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
async def _stage_config_global(
    config: config_lib.Config,
) -> AsyncIterator[None]:
    yield
    get_config.cache_clear()


@stage_config_plugin("50_session")
@contextlib.asynccontextmanager
async def _stage_config_session_service(
    config: config_lib.Config,
) -> AsyncIterator[None]:
    session_service = await get_session_service()
    async with session_service.stage_config(config):
        yield


@startup_plugin("20_alert")
async def _startup_alert_driver() -> None:
    (await get_alert_driver()).start()


@startup_plugin("20_resume")
async def _startup_resume_service() -> None:
    (await get_resume_service()).start()


@startup_plugin("20_request")
async def _startup_request_service() -> None:
    (await get_request_service()).start()


@startup_plugin("30_load")
async def _load_resume_data() -> None:
    await (await get_resume_service()).load()


@shutdown_plugin("60_request")
async def _shutdown_drain_requests() -> None:
    request_service = await get_request_service()
    request_service.close()
    await request_service.wait_closed()


@shutdown_plugin("70_session")
async def _shutdown_pause_session() -> None:
    session = await get_session()
    _LOG.info("shutdown: pausing libtorrent session")
    # Does not block
    session.pause()


@shutdown_plugin("80_resume")
async def _shutdown_save_resume_data() -> None:
    resume_service = await get_resume_service()
    resume_service.close()
    await resume_service.wait_closed()


@shutdown_plugin("90_alerts")
async def _shutdown_drain_alerts() -> None:
    # Wait for alert consumers to finish
    alert_driver = await get_alert_driver()
    alert_driver.close()
    await alert_driver.wait_closed()


@shutdown_plugin("98_clear")
async def _shutdown_clear_caches() -> None:
    caches.clear_all()
