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
from collections.abc import Collection
from collections.abc import Iterator
import contextlib
import logging
from typing import Any

import libtorrent as lt

from . import config as config_lib
from . import ltpy

_LOG = logging.getLogger()

_OVERRIDES = {
    "announce_ip": "",
    "handshake_client_version": "",
    "alert_queue_size": 2**31 - 1,
}

_BLACKLIST = {
    "user_agent",
    "peer_fingerprint",
}


@contextlib.contextmanager
def _translate_exceptions() -> Iterator[None]:
    try:
        with ltpy.translate_exceptions():
            yield
    except (KeyError, TypeError, ltpy.Error) as exc:
        raise config_lib.InvalidConfigError(str(exc)) from exc


def parse_config(config: config_lib.Config) -> dict[str, Any]:
    config.setdefault("session_settings_base", "default_settings")

    settings_base_name = config.require_str("session_settings_base")
    if settings_base_name not in ("default_settings", "high_performance_seed"):
        raise config_lib.InvalidConfigError(
            f'no settings pack named "{settings_base_name}"'
        )
    settings: dict[str, Any] = getattr(lt, settings_base_name)()

    for key, value in config.items():
        if not key.startswith("session_"):
            continue
        key = key[len("session_") :]
        if key == "settings_base":
            continue

        if key in _BLACKLIST:
            continue

        if key not in settings:
            raise config_lib.InvalidConfigError(f"no setting named {key}")
        if settings[key].__class__ != value.__class__:
            raise config_lib.InvalidConfigError(
                f"{key} should be {settings[key].__class__}, " f"not {value.__class__}"
            )

        settings[key] = value

    # Update our static overrides
    settings.update(_OVERRIDES)

    return settings


_LOG2 = {1 << i: i for i in range(64)}


def _get_mask_bits(mask: int) -> Collection[int]:
    bits = set()
    while mask != 0:
        mask_without_one_bit = mask & (mask - 1)
        one_bit_mask = mask & ~mask_without_one_bit
        bits.add(_LOG2[one_bit_mask])
        mask = mask_without_one_bit
    return bits


_ALERT_MASK_NAME: dict[int, str] = {}


def _init_alert_mask_name() -> None:
    for name in dir(lt.alert.category_t):
        if name.startswith("_"):
            continue
        mask = getattr(lt.alert.category_t, name)
        if mask not in _LOG2:
            continue
        _ALERT_MASK_NAME[mask] = name


_init_alert_mask_name()
del _init_alert_mask_name


class SessionService:
    def __init__(self, *, alert_mask: int = 0, config: config_lib.Config = None):
        self._alert_mask_bit_count: dict[int, int] = {}
        self._inc_alert_mask_bits(alert_mask)
        if config is None:
            config = config_lib.Config()

        with _translate_exceptions():
            self._settings = parse_config(config)
            self._config_alert_mask: int = self._settings["alert_mask"]
            self._settings["alert_mask"] |= alert_mask
            self._inc_alert_mask_bits(self._config_alert_mask)
            self.session = lt.session(self._settings)

    def _inc_alert_mask_bits(self, alert_mask: int) -> None:
        for bit in _get_mask_bits(alert_mask):
            self._alert_mask_bit_count[bit] = self._alert_mask_bit_count.get(bit, 0) + 1

    def _dec_alert_mask_bits(self, alert_mask: int) -> None:
        for bit in _get_mask_bits(alert_mask):
            self._alert_mask_bit_count[bit] -= 1
            if self._alert_mask_bit_count[bit] == 0:
                self._alert_mask_bit_count.pop(bit)

    def inc_alert_mask(self, alert_mask: int) -> None:
        self._inc_alert_mask_bits(alert_mask)
        # Can't fail to update alert mask (?)
        self._update_alert_mask()

    def dec_alert_mask(self, alert_mask: int) -> None:
        self._dec_alert_mask_bits(alert_mask)
        # Can't fail to update alert mask (?)
        self._update_alert_mask()

    def _update_alert_mask(self) -> None:
        alert_mask = self._get_alert_mask()
        self._apply_settings({"alert_mask": alert_mask})
        self._settings["alert_mask"] = alert_mask

    def _get_alert_mask(self) -> int:
        alert_mask = 0
        for bit in self._alert_mask_bit_count:
            alert_mask |= 1 << bit
        return alert_mask

    def _apply_settings(self, settings: dict[str, Any]) -> None:
        deltas = dict(set(settings.items()) - set(self._settings.items()))
        if not deltas:
            return
        if _LOG.isEnabledFor(logging.DEBUG):
            delta_alert_mask = settings["alert_mask"] ^ self._settings["alert_mask"]
            for bit in _get_mask_bits(delta_alert_mask):
                mask = 1 << bit
                name = _ALERT_MASK_NAME.get(mask, mask)
                if settings["alert_mask"] & mask:
                    _LOG.debug("enabling alerts: %s", name)
                else:
                    _LOG.debug("disabling alerts: %s", name)
        # As far as I can tell, apply_settings never partially fails
        self.session.apply_settings(deltas)

    @contextlib.asynccontextmanager
    async def stage_config(self, config: config_lib.Config) -> AsyncIterator[None]:
        settings = parse_config(config)

        yield
        config_alert_mask: int = settings["alert_mask"]
        self._dec_alert_mask_bits(self._config_alert_mask)
        self._inc_alert_mask_bits(config_alert_mask)
        settings["alert_mask"] = self._get_alert_mask()
        self._apply_settings(settings)
        self._settings = settings
        self._config_alert_mask = config_alert_mask
