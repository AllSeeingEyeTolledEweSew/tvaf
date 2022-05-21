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
import pathlib
import tempfile
from typing import AsyncIterator
import unittest

from tvaf import config as config_lib

from . import lib


class TestReadWrite(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = pathlib.Path(self.tempdir.name) / "config.json"

    def tearDown(self) -> None:
        lib.cleanup_with_windows_fix(self.tempdir, timeout=5)

    def test_from_disk(self) -> None:
        self.path.write_text('{"text_field": "value", ' '"numeric_field": 123}')

        config = asyncio.run(config_lib.Config.from_disk(self.path))

        self.assertEqual(
            config, config_lib.Config(text_field="value", numeric_field=123)
        )

    def test_from_disk_invalid_json(self) -> None:
        self.path.write_text("invalid json")

        with self.assertRaises(config_lib.InvalidConfigError):
            asyncio.run(config_lib.Config.from_disk(self.path))

    def test_write(self) -> None:
        config = config_lib.Config(text_field="value", numeric_field=123)
        asyncio.run(config.write_to_disk(self.path))

        config_text = self.path.read_text()

        self.assertEqual(
            config_text,
            "{\n" '    "numeric_field": 123,\n' '    "text_field": "value"\n' "}",
        )


class TestAccessors(unittest.TestCase):
    def test_get_int(self) -> None:
        config = config_lib.Config(key=123)
        self.assertEqual(config.get_int("key"), 123)

    def test_get_int_missing(self) -> None:
        config = config_lib.Config()
        self.assertEqual(config.get_int("key"), None)

    def test_get_int_invalid(self) -> None:
        config = config_lib.Config(key="not an int")
        with self.assertRaises(config_lib.InvalidConfigError):
            config.get_int("key")

    def test_get_str(self) -> None:
        config = config_lib.Config(key="value")
        self.assertEqual(config.get_str("key"), "value")

    def test_get_str_missing(self) -> None:
        config = config_lib.Config()
        self.assertEqual(config.get_str("key"), None)

    def test_get_str_invalid(self) -> None:
        config = config_lib.Config(key=123)
        with self.assertRaises(config_lib.InvalidConfigError):
            config.get_str("key")

    def test_get_bool(self) -> None:
        config = config_lib.Config(key=True)
        self.assertEqual(config.get_bool("key"), True)

    def test_get_bool_missing(self) -> None:
        config = config_lib.Config()
        self.assertEqual(config.get_bool("key"), None)

    def test_get_bool_invalid(self) -> None:
        config = config_lib.Config(key=1)
        with self.assertRaises(config_lib.InvalidConfigError):
            config.get_bool("key")

    def test_require_int(self) -> None:
        config = config_lib.Config(key=123)
        self.assertEqual(config.require_int("key"), 123)

    def test_require_int_missing(self) -> None:
        config = config_lib.Config()
        with self.assertRaises(config_lib.InvalidConfigError):
            config.require_int("key")

    def test_require_int_invalid(self) -> None:
        config = config_lib.Config(key="not an int")
        with self.assertRaises(config_lib.InvalidConfigError):
            config.require_int("key")

    def test_require_str(self) -> None:
        config = config_lib.Config(key="value")
        self.assertEqual(config.require_str("key"), "value")

    def test_require_str_missing(self) -> None:
        config = config_lib.Config()
        with self.assertRaises(config_lib.InvalidConfigError):
            config.require_str("key")

    def test_require_str_invalid(self) -> None:
        config = config_lib.Config(key=123)
        with self.assertRaises(config_lib.InvalidConfigError):
            config.require_str("key")

    def test_require_bool(self) -> None:
        config = config_lib.Config(key=True)
        self.assertEqual(config.require_bool("key"), True)

    def test_require_bool_missing(self) -> None:
        config = config_lib.Config()
        with self.assertRaises(config_lib.InvalidConfigError):
            config.require_bool("key")

    def test_require_bool_invalid(self) -> None:
        config = config_lib.Config(key=1)
        with self.assertRaises(config_lib.InvalidConfigError):
            config.require_bool("key")


class Receiver:
    def __init__(self):
        self.config = config_lib.Config()

    @contextlib.asynccontextmanager
    async def stage_config(self, config: config_lib.Config) -> AsyncIterator[None]:
        yield
        self.config = config


class DummyException(Exception):

    pass


def _raise_dummy() -> None:
    raise DummyException()


class FailReceiver:
    def __init__(self):
        self.config = config_lib.Config()

    @contextlib.asynccontextmanager
    async def stage_config(self, _config: config_lib.Config) -> AsyncIterator[None]:
        _raise_dummy()
        yield


class TestStageConfig(unittest.TestCase):
    def test_fail(self) -> None:
        config = config_lib.Config(new=True)

        good_receiver = Receiver()
        fail_receiver = FailReceiver()

        # fail_receiver should cause an exception to be raised
        async def stage_good_fail() -> None:
            async with config_lib.stage_config(
                config, good_receiver.stage_config, fail_receiver.stage_config
            ):
                pass

        with self.assertRaises(DummyException):
            asyncio.run(stage_good_fail())

        # fail_receiver should prevent good_receiver from updating
        self.assertEqual(good_receiver.config, config_lib.Config())

        # Order should be independent
        async def stage_fail_good() -> None:
            async with config_lib.stage_config(
                config, fail_receiver.stage_config, good_receiver.stage_config
            ):
                pass

        with self.assertRaises(DummyException):
            asyncio.run(stage_fail_good())

        self.assertEqual(good_receiver.config, config_lib.Config())

    def test_success(self) -> None:
        config = config_lib.Config(new=True)

        receiver1 = Receiver()
        receiver2 = Receiver()

        async def stage_1_2() -> None:
            async with config_lib.stage_config(
                config, receiver1.stage_config, receiver2.stage_config
            ):
                pass

        asyncio.run(stage_1_2())

        self.assertEqual(receiver1.config, config)
        self.assertEqual(receiver2.config, config)
