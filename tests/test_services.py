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
from collections.abc import Iterator
import contextlib
import os
import pathlib
import tempfile
import unittest

import asyncstdlib
import libtorrent as lt

from tvaf import concurrency
from tvaf import config as config_lib
from tvaf import resume as resume_lib
from tvaf import services
from tvaf.services import atp as atp_services

from . import lib
from . import tdummy


class TemporaryDirectoryTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.cwd = await asyncio.to_thread(pathlib.Path.cwd)
        self.tempdir = await asyncio.to_thread(tempfile.TemporaryDirectory)
        await asyncio.to_thread(os.chdir, self.tempdir.name)
        self.config = lib.create_isolated_config()
        await self.config.write_to_disk(services.CONFIG_PATH)

    async def asyncTearDown(self) -> None:
        await asyncio.to_thread(os.chdir, self.cwd)
        await asyncio.to_thread(self.tempdir.cleanup)


class LifespanTest(TemporaryDirectoryTestCase):
    @contextlib.asynccontextmanager
    async def start_stop_session(self) -> AsyncIterator[None]:
        await asyncio.wait_for(services.startup(), 60)
        yield
        await asyncio.wait_for(services.shutdown(), 60)

    async def test_with_config(self) -> None:
        self.assertTrue(await asyncio.to_thread(services.CONFIG_PATH.is_file))
        async with self.start_stop_session():
            pass

    async def test_empty_directory(self) -> None:
        # this technically breaks isolation (non-isolated config listens on
        # default ports and will bootstrap dht, etc), but it must be tested!
        await asyncio.to_thread(services.CONFIG_PATH.unlink)
        contents = await asyncstdlib.list(
            concurrency.iter_in_thread(pathlib.Path().iterdir())
        )
        self.assertEqual(contents, [])
        async with self.start_stop_session():
            pass

    async def test_set_config(self) -> None:
        async with self.start_stop_session():
            self.config["__test_key__"] = "value"

            await asyncio.wait_for(services.set_config(self.config), 60)

            # Test loaded into available config
            config = await asyncio.wait_for(services.get_config(), 60)
            self.assertEqual(config["__test_key__"], "value")
            # Test written to disk
            config = await config_lib.Config.from_disk(services.CONFIG_PATH)
            self.assertEqual(config, self.config)

    async def test_set_invalid_config(self) -> None:
        async with self.start_stop_session():
            self.config["torrent_default_storage_mode"] = "invalid"
            with self.assertRaises(config_lib.InvalidConfigError):
                await asyncio.wait_for(services.set_config(self.config), 60)
            config = await asyncio.wait_for(services.get_config(), 60)
            self.assertNotEqual(
                config.get_str("torrent_default_storage_mode"), "invalid"
            )

    async def test_save_and_load_resume_data(self) -> None:
        async with self.start_stop_session():
            session = await asyncio.wait_for(services.get_session(), 60)
            atp = tdummy.DEFAULT.atp()
            atp.save_path = self.tempdir.name
            session.async_add_torrent(atp)

        def get_resume_data() -> Iterator[lt.add_torrent_params]:
            with services.resume_db_pool() as conn:
                yield from resume_lib.iter_resume_data_from_db(conn)

        resume_data = await asyncstdlib.list(
            concurrency.iter_in_thread(get_resume_data())
        )

        self.assertEqual(len(resume_data), 1)

        async with self.start_stop_session():
            session = await asyncio.wait_for(services.get_session(), 60)
            torrents = await asyncio.to_thread(session.get_torrents)
            self.assertEqual(len(torrents), 1)

    async def test_process_lock(self) -> None:
        async with self.start_stop_session():
            with self.assertRaises(AssertionError):
                await asyncio.wait_for(services.startup(), 60)


class TestDefaultATP(TemporaryDirectoryTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        await asyncio.wait_for(services.startup(), 60)

    async def asyncTearDown(self) -> None:
        await asyncio.wait_for(services.shutdown(), 60)
        await super().asyncTearDown()

    async def test_config_defaults(self) -> None:
        save_path = str(await asyncio.to_thread(pathlib.Path("download").resolve))
        config = await asyncio.wait_for(services.get_config(), 60)
        self.assertEqual(config["torrent_default_save_path"], save_path)

        atp = await asyncio.wait_for(atp_services.get_default(), 60)

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
        await asyncio.wait_for(services.set_config(config), 60)

        atp = await asyncio.wait_for(atp_services.get_default(), 60)

        self.assertEqual(
            pathlib.Path(atp.save_path).resolve(),
            pathlib.Path(self.tempdir.name).resolve(),
        )
        self.assertEqual(
            atp.flags,
            lt.torrent_flags.default_flags & ~lt.torrent_flags.apply_ip_filter,
        )
        self.assertEqual(atp.storage_mode, lt.storage_mode_t.storage_mode_allocate)

    async def test_save_path_loop(self) -> None:
        bad_link = pathlib.Path("bad_link")
        await asyncio.to_thread(bad_link.symlink_to, bad_link, target_is_directory=True)

        config = config_lib.Config(torrent_default_save_path=str(bad_link))
        with self.assertRaises(config_lib.InvalidConfigError):
            await asyncio.wait_for(services.set_config(config), 60)

    async def test_flags_apply_ip_filter_null(self) -> None:
        config = config_lib.Config(torrent_default_flags_apply_ip_filter=None)
        with self.assertRaises(config_lib.InvalidConfigError):
            await asyncio.wait_for(services.set_config(config), 60)

    async def test_storage_mode_invalid(self) -> None:
        config = config_lib.Config(torrent_default_storage_mode="invalid")
        with self.assertRaises(config_lib.InvalidConfigError):
            await asyncio.wait_for(services.set_config(config), 60)
