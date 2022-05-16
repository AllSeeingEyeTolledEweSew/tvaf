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


import unittest

import libtorrent as lt

from tvaf import config as config_lib
from tvaf import session as session_lib

from . import lib


class DummyException(Exception):

    pass


def _raise_dummy() -> None:
    raise DummyException()


class TestSession(unittest.IsolatedAsyncioTestCase):
    @unittest.skip("determining valid settings is broken")
    async def test_session(self) -> None:
        init_alert_mask = lt.alert_category.error | lt.alert_category.peer
        config = lib.create_isolated_config()
        config["session_handshake_client_version"] = "test-version"
        session_service = session_lib.SessionService(
            config=config, alert_mask=init_alert_mask
        )

        # Test default config is added
        session_service.session.get_settings()
        self.assertEqual(config["session_settings_base"], "default_settings")

    async def test_alert_mask(self) -> None:
        config = lib.create_isolated_config()
        config["session_alert_mask"] = 2

        session_service = session_lib.SessionService(alert_mask=1, config=config)

        # Test required mask was added
        settings = session_service.session.get_settings()
        self.assertEqual(settings["alert_mask"], 1 | 2)

        # Test we can add a runtime mask
        session_service.inc_alert_mask(1 | 8)
        settings = session_service.session.get_settings()
        self.assertEqual(settings["alert_mask"], 1 | 2 | 8)

        # Test we can unset alert mask via config
        config["session_alert_mask"] = 0
        async with session_service.stage_config(config):
            pass
        settings = session_service.session.get_settings()
        self.assertEqual(settings["alert_mask"], 1 | 8)

        # Test we can change alert mask via config
        config["session_alert_mask"] = 4
        async with session_service.stage_config(config):
            pass
        settings = session_service.session.get_settings()
        self.assertEqual(settings["alert_mask"], 1 | 4 | 8)

        # Test we can remove the runtime mask
        session_service.dec_alert_mask(1 | 8)
        settings = session_service.session.get_settings()
        self.assertEqual(settings["alert_mask"], 1 | 4)

    @unittest.skip("determining valid settings is broken")
    async def test_overrides(self) -> None:
        config = lib.create_isolated_config()
        config["session_handshake_client_version"] = "test-version"
        session_service = session_lib.SessionService(config=config)

        # Test overrides are applied
        settings = session_service.session.get_settings()
        self.assertEqual(settings["handshake_client_version"], "")

    async def test_blacklist(self) -> None:
        config = lib.create_isolated_config()
        config["session_user_agent"] = "test"
        session_service = session_lib.SessionService(config=config)

        # Test blacklisted setting gets replaced by libtorrent default
        settings = session_service.session.get_settings()
        self.assertNotEqual(settings["user_agent"], "test")

    async def test_reconfigure(self) -> None:
        config = lib.create_isolated_config()
        session_service = session_lib.SessionService(config=config)

        # Sanity check: close_redundant_connections should be True by default
        settings = session_service.session.get_settings()
        self.assertEqual(settings["close_redundant_connections"], True)

        # Change config
        config["session_close_redundant_connections"] = False
        async with session_service.stage_config(config):
            pass

        settings = session_service.session.get_settings()
        self.assertEqual(settings["close_redundant_connections"], False)

        # Test we can set_config with no changes
        async with session_service.stage_config(config):
            pass
        settings = session_service.session.get_settings()
        self.assertEqual(settings["close_redundant_connections"], False)

    async def test_stage_revert(self) -> None:
        config = lib.create_isolated_config()
        session_service = session_lib.SessionService(config=config)

        config["session_close_redundant_connections"] = False

        async def stage_and_fail() -> None:
            async with session_service.stage_config(config):
                _raise_dummy()

        with self.assertRaises(DummyException):
            await stage_and_fail()

        settings = session_service.session.get_settings()
        self.assertEqual(settings["close_redundant_connections"], True)

    @unittest.skip("determining valid settings is broken")
    async def test_settings_base(self) -> None:
        config = lib.create_isolated_config()
        config["session_settings_base"] = "high_performance_seed"
        session_service = session_lib.SessionService(config=config)

        settings = session_service.session.get_settings()

        # Check settings pack was applied as default
        self.assertEqual(
            settings["cache_size"], lt.high_performance_seed()["cache_size"]
        )

        # Check base pack name didn't get overwritten
        self.assertEqual(config["session_settings_base"], "high_performance_seed")

    async def test_settings_base_invalid(self) -> None:
        with self.assertRaises(config_lib.InvalidConfigError):
            session_lib.SessionService(
                config=config_lib.Config(session_settings_base="invalid")
            )

    async def test_setting_invalid_type(self) -> None:
        with self.assertRaises(config_lib.InvalidConfigError):
            session_lib.SessionService(
                config=config_lib.Config(session_cache_size="invalid")
            )

    async def test_alert_mask_invalid_type(self) -> None:
        with self.assertRaises(config_lib.InvalidConfigError):
            session_lib.SessionService(
                config=config_lib.Config(session_alert_mask="invalid")
            )
