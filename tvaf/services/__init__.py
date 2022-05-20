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
import logging
import pathlib
from typing import Any
from typing import AsyncContextManager
from typing import AsyncIterator
from typing import Awaitable
from typing import Callable

import libtorrent as lt

from .. import concurrency
from .. import config as config_lib
from .. import driver as driver_lib
from .. import lifecycle
from .. import plugins
from .. import request as request_lib
from .. import resume as resume_lib
from .. import session as session_lib

_LOG = logging.getLogger(__name__)

CONFIG_PATH = pathlib.Path("config.json")
RESUME_DATA_PATH = pathlib.Path("resume")
DEFAULT_DOWNLOAD_PATH = pathlib.Path("download")


Startup = Callable[[], Awaitable]
_STARTUP_FUNCS: plugins.Funcs[Startup] = plugins.Funcs("tvaf.services.startup")
startup_plugin = _STARTUP_FUNCS.decorator


async def startup() -> None:
    for _, func in sorted(_STARTUP_FUNCS.get().items()):
        await func()


Shutdown = Callable[[], Awaitable]
_SHUTDOWN_FUNCS: plugins.Funcs[Shutdown] = plugins.Funcs("tvaf.services.shutdown")
shutdown_plugin = _SHUTDOWN_FUNCS.decorator


async def shutdown() -> None:
    for _, func in sorted(_SHUTDOWN_FUNCS.get().items()):
        await func()


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


DefaultATP = Callable[[lt.add_torrent_params], Awaitable]
_DEFAULT_ATP_FUNCS: plugins.Funcs[DefaultATP] = plugins.Funcs(
    "tvaf.services.default_atp"
)
default_atp_plugin = _DEFAULT_ATP_FUNCS.decorator


async def get_default_atp() -> lt.add_torrent_params:
    atp = lt.add_torrent_params()
    for _, func in sorted(_DEFAULT_ATP_FUNCS.get().items()):
        await func(atp)
    return atp


ConfigureATP = Callable[[lt.add_torrent_params], Awaitable]
_CONFIGURE_ATP_FUNCS: plugins.Funcs[ConfigureATP] = plugins.Funcs(
    "tvaf.services.configure_atp"
)
configure_atp_plugin = _CONFIGURE_ATP_FUNCS.decorator


async def configure_atp(atp: lt.add_torrent_params) -> None:
    for _, func in sorted(_CONFIGURE_ATP_FUNCS.get().items()):
        await func(atp)


_process_locked = False


@lifecycle.asingleton()
async def get_config() -> config_lib.Config:
    try:
        return await config_lib.Config.from_disk(CONFIG_PATH)
    except FileNotFoundError:
        return config_lib.Config()


@lifecycle.asingleton()
async def get_session_service() -> session_lib.SessionService:
    return session_lib.SessionService(config=await get_config())


@lifecycle.asingleton()
async def get_session() -> lt.session:
    return (await get_session_service()).session


@lifecycle.asingleton()
async def get_alert_driver() -> driver_lib.AlertDriver:
    return driver_lib.AlertDriver(session_service=await get_session_service())


@lifecycle.asingleton()
async def get_resume_service() -> resume_lib.ResumeService:
    return resume_lib.ResumeService(
        session=await get_session(),
        alert_driver=await get_alert_driver(),
        path=RESUME_DATA_PATH,
    )


@lifecycle.asingleton()
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
            await concurrency.to_thread(tmp_path.replace, CONFIG_PATH)
            _LOG.info("config: wrote %s", CONFIG_PATH.resolve())
        except OSError:
            _LOG.exception("couldn't write %s", CONFIG_PATH.resolve())
    finally:
        try:
            await concurrency.to_thread(tmp_path.unlink)
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


@startup_plugin("00_process")
async def _lock_process() -> None:
    global _process_locked
    _LOG.debug("startup: acquiring process lock")
    if _process_locked:
        raise AssertionError("only one instance allowed")
    _process_locked = True


@shutdown_plugin("99_process")
async def _unlock_process() -> None:
    global _process_locked
    assert _process_locked
    _LOG.debug("shutdown: releasing process lock")
    _process_locked = False


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
    # Load resume data
    session = await get_session()
    _LOG.info("startup: loading resume data")
    async for atp in resume_lib.iter_resume_data_from_disk(RESUME_DATA_PATH):
        # Does not block
        session.async_add_torrent(atp)


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
    lifecycle.clear()


async def _get_atp_defaults_from_config(
    config: config_lib.Config,
) -> dict[str, Any]:
    config.setdefault("torrent_default_save_path", str(DEFAULT_DOWNLOAD_PATH))

    atp_defaults: dict[str, Any] = {}

    save_path = pathlib.Path(config.require_str("torrent_default_save_path"))
    try:
        # Raises RuntimeError on symlink loops
        save_path = await concurrency.to_thread(save_path.resolve)
    except RuntimeError as exc:
        raise config_lib.InvalidConfigError(str(exc)) from exc

    config["torrent_default_save_path"] = str(save_path)
    atp_defaults["save_path"] = str(save_path)

    name_to_flag = {
        "apply_ip_filter": lt.torrent_flags.apply_ip_filter,
    }

    for name, flag in name_to_flag.items():
        key = f"torrent_default_flags_{name}"
        value = config.get_bool(key)
        if value is None:
            continue
        atp_defaults.setdefault("flags", lt.torrent_flags.default_flags)
        if value:
            atp_defaults["flags"] |= flag
        else:
            atp_defaults["flags"] &= ~flag

    maybe_name = config.get_str("torrent_default_storage_mode")
    if maybe_name is not None:
        full_name = f"storage_mode_{maybe_name}"
        mode = lt.storage_mode_t.names.get(full_name)
        if mode is None:
            raise config_lib.InvalidConfigError(f"invalid storage mode {maybe_name}")
        atp_defaults["storage_mode"] = mode
    return atp_defaults


@lifecycle.asingleton()
async def _get_atp_defaults() -> dict[str, Any]:
    return await _get_atp_defaults_from_config(await get_config())


@startup_plugin("10_default_atp")
async def _startup_config_default_atp() -> None:
    # Parse existing config
    await _get_atp_defaults()


@stage_config_plugin("50_default_atp")
@contextlib.asynccontextmanager
async def _stage_config_default_atp(
    config: config_lib.Config,
) -> AsyncIterator[None]:
    await _get_atp_defaults_from_config(config)
    yield
    _get_atp_defaults.cache_clear()


@default_atp_plugin("50_config")
async def _default_atp_from_config(atp: lt.add_torrent_params) -> None:
    defaults = await _get_atp_defaults()
    for key, value in defaults.items():
        setattr(atp, key, value)
