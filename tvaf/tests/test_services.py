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

import contextlib
import os
import pathlib
import tempfile
from typing import AsyncIterator
import unittest

import libtorrent as lt

from tvaf import concurrency
from tvaf import config as config_lib
from tvaf import resume as resume_lib
from tvaf import services

from . import lib
from . import tdummy


class TemporaryDirectoryTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.cwd = await concurrency.to_thread(pathlib.Path.cwd)
        self.tempdir = await concurrency.to_thread(tempfile.TemporaryDirectory)
        await concurrency.to_thread(os.chdir, self.tempdir.name)
        self.config = lib.create_isolated_config()
        await self.config.write_to_disk(services.CONFIG_PATH)

    async def asyncTearDown(self) -> None:
        await concurrency.to_thread(os.chdir, self.cwd)
        await concurrency.to_thread(self.tempdir.cleanup)


class LifespanTest(TemporaryDirectoryTestCase):
    @contextlib.asynccontextmanager
    async def start_stop_session(self) -> AsyncIterator[None]:
        await services.startup()
        yield
        await services.shutdown()

    async def test_with_config(self) -> None:
        self.assertTrue(await concurrency.to_thread(services.CONFIG_PATH.is_file))
        async with self.start_stop_session():
            pass

    async def test_empty_directory(self) -> None:
        # this technically breaks isolation (non-isolated config listens on
        # default ports and will bootstrap dht, etc), but it must be tested!
        await concurrency.to_thread(services.CONFIG_PATH.unlink)
        contents = await concurrency.alist(
            concurrency.iter_in_thread(pathlib.Path().iterdir())
        )
        self.assertEqual(contents, [])
        async with self.start_stop_session():
            pass

    async def test_set_config(self) -> None:
        async with self.start_stop_session():
            self.config["__test_key__"] = "value"

            await services.set_config(self.config)

            # Test loaded into available config
            config = await services.get_config()
            self.assertEqual(config["__test_key__"], "value")
            # Test written to disk
            config = await config_lib.Config.from_disk(services.CONFIG_PATH)
            self.assertEqual(config, self.config)

    async def test_set_invalid_config(self) -> None:
        async with self.start_stop_session():
            self.config["torrent_default_storage_mode"] = "invalid"
            with self.assertRaises(config_lib.InvalidConfigError):
                await services.set_config(self.config)
            config = await services.get_config()
            self.assertNotEqual(
                config.get_str("torrent_default_storage_mode"), "invalid"
            )

    async def test_save_and_load_resume_data(self) -> None:
        async with self.start_stop_session():
            session = await services.get_session()
            atp = tdummy.DEFAULT.atp()
            atp.save_path = self.tempdir.name
            session.async_add_torrent(atp)

        resume_data = await concurrency.alist(
            resume_lib.iter_resume_data_from_disk(services.RESUME_DATA_PATH)
        )
        self.assertEqual(len(resume_data), 1)

        async with self.start_stop_session():
            session = await services.get_session()
            torrents = await concurrency.to_thread(session.get_torrents)
            self.assertEqual(len(torrents), 1)

    async def test_process_lock(self) -> None:
        async with self.start_stop_session():
            with self.assertRaises(AssertionError):
                await services.startup()


class TestDefaultATP(TemporaryDirectoryTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        await services.startup()

    async def asyncTearDown(self) -> None:
        await services.shutdown()
        await super().asyncTearDown()

    async def test_config_defaults(self) -> None:
        save_path = str(await concurrency.to_thread(pathlib.Path("download").resolve))
        config = await services.get_config()
        self.assertEqual(config["torrent_default_save_path"], save_path)

        atp = await services.get_default_atp()

        self.assertEqual(atp.save_path, save_path)
        self.assertEqual(atp.flags, lt.torrent_flags.default_flags)
        self.assertEqual(atp.storage_mode, lt.add_torrent_params().storage_mode)

    async def test_set_non_defaults(self) -> None:
        # Set all non-default configs
        config = config_lib.Config(
            torrent_default_save_path=self.tempdir.name,
            torrent_default_flags_apply_ip_filter=False,
            torrent_default_storage_mode="allocate",
        )
        await services.set_config(config)

        atp = await services.get_default_atp()

        self.assertEqual(atp.save_path, self.tempdir.name)
        self.assertEqual(
            atp.flags,
            lt.torrent_flags.default_flags & ~lt.torrent_flags.apply_ip_filter,
        )
        self.assertEqual(atp.storage_mode, lt.storage_mode_t.storage_mode_allocate)

    async def test_save_path_loop(self) -> None:
        bad_link = pathlib.Path("bad_link")
        await concurrency.to_thread(
            bad_link.symlink_to, bad_link, target_is_directory=True
        )

        config = config_lib.Config(torrent_default_save_path=str(bad_link))
        with self.assertRaises(config_lib.InvalidConfigError):
            await services.set_config(config)

    async def test_flags_apply_ip_filter_null(self) -> None:
        config = config_lib.Config(torrent_default_flags_apply_ip_filter=None)
        with self.assertRaises(config_lib.InvalidConfigError):
            await services.set_config(config)

    async def test_storage_mode_invalid(self) -> None:
        config = config_lib.Config(torrent_default_storage_mode="invalid")
        with self.assertRaises(config_lib.InvalidConfigError):
            await services.set_config(config)
