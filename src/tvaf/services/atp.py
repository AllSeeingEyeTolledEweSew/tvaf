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

from collections.abc import AsyncIterator
from collections.abc import Awaitable
import contextlib
import logging
import pathlib
from typing import Any
from typing import Callable

import libtorrent as lt

from tvaf import caches

from .. import concurrency
from .. import config as config_lib
from .. import plugins
from .. import services

_LOG = logging.getLogger(__name__)
DEFAULT_DOWNLOAD_PATH = pathlib.Path("download")


Default = Callable[[lt.add_torrent_params], Awaitable]
_DEFAULT_FUNCS: plugins.Funcs[Default] = plugins.Funcs("tvaf.services.atp.default")
default_plugin = _DEFAULT_FUNCS.decorator


async def get_default() -> lt.add_torrent_params:
    atp = lt.add_torrent_params()
    for _, func in sorted(_DEFAULT_FUNCS.get().items()):
        await func(atp)
    return atp


Configure = Callable[[lt.add_torrent_params], Awaitable]
_CONFIGURE_FUNCS: plugins.Funcs[Configure] = plugins.Funcs(
    "tvaf.services.atp.configure"
)
configure_plugin = _CONFIGURE_FUNCS.decorator


async def configure(atp: lt.add_torrent_params) -> None:
    for _, func in sorted(_CONFIGURE_FUNCS.get().items()):
        await func(atp)


async def _get_defaults_from_config(
    config: config_lib.Config,
) -> dict[str, Any]:
    config.setdefault("torrent_default_save_path", str(DEFAULT_DOWNLOAD_PATH))

    defaults: dict[str, Any] = {}

    save_path = pathlib.Path(config.require_str("torrent_default_save_path"))
    try:
        # Raises RuntimeError on symlink loops
        save_path = await concurrency.to_thread(save_path.resolve)
    except RuntimeError as exc:
        raise config_lib.InvalidConfigError(str(exc)) from exc

    config["torrent_default_save_path"] = str(save_path)
    defaults["save_path"] = str(save_path)

    name_to_flag = {
        "apply_ip_filter": lt.torrent_flags.apply_ip_filter,
    }

    for name, flag in name_to_flag.items():
        key = f"torrent_default_flags_{name}"
        value = config.get_bool(key)
        if value is None:
            continue
        defaults.setdefault("flags", lt.torrent_flags.default_flags)
        if value:
            defaults["flags"] |= flag
        else:
            defaults["flags"] &= ~flag

    maybe_name = config.get_str("torrent_default_storage_mode")
    if maybe_name is not None:
        full_name = f"storage_mode_{maybe_name}"
        mode = lt.storage_mode_t.names.get(full_name)
        if mode is None:
            raise config_lib.InvalidConfigError(f"invalid storage mode {maybe_name}")
        defaults["storage_mode"] = mode
    return defaults


@caches.asingleton()
async def _get_defaults() -> dict[str, Any]:
    return await _get_defaults_from_config(await services.get_config())


@services.startup_plugin("10_default_atp")
async def _startup_config_default() -> None:
    # Parse existing config
    await _get_defaults()


@services.stage_config_plugin("50_default_atp")
@contextlib.asynccontextmanager
async def _stage_config_default(
    config: config_lib.Config,
) -> AsyncIterator[None]:
    await _get_defaults_from_config(config)
    yield
    _get_defaults.cache_clear()


@default_plugin("50_config")
async def _default_from_config(atp: lt.add_torrent_params) -> None:
    defaults = await _get_defaults()
    for key, value in defaults.items():
        setattr(atp, key, value)
