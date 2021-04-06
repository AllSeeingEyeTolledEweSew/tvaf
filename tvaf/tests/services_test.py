# Copyright (c) 2020 AllSeeingEyeTolledEweSew
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

import contextlib
import os
import pathlib
import tempfile
from typing import Iterator
import unittest

import libtorrent as lt

from tvaf import config as config_lib
from tvaf import resume as resume_lib
from tvaf import services

from . import lib
from . import tdummy


class TemporaryDirectoryTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.cwd = pathlib.Path.cwd()
        self.tempdir = tempfile.TemporaryDirectory()
        os.chdir(self.tempdir.name)
        self.config = lib.create_isolated_config()
        self.config.write_to_disk(services.CONFIG_PATH)

    def tearDown(self) -> None:
        os.chdir(self.cwd)
        self.tempdir.cleanup()


class LifespanTest(TemporaryDirectoryTestCase):
    @contextlib.contextmanager
    def start_stop_session(self) -> Iterator[None]:
        services.startup()
        yield
        services.shutdown()

    def test_with_config(self) -> None:
        self.assertTrue(services.CONFIG_PATH.is_file())
        with self.start_stop_session():
            pass

    def test_empty_directory(self) -> None:
        # This technically breaks isolation, but we do need to test it
        services.CONFIG_PATH.unlink()
        self.assertEqual(list(pathlib.Path().iterdir()), [])
        with self.start_stop_session():
            pass

    def test_set_config(self) -> None:
        with self.start_stop_session():
            self.config["__test_key__"] = "value"

            services.set_config(self.config)

            # Test loaded into available config
            self.assertEqual(services.get_config()["__test_key__"], "value")
            # Test written to disk
            self.assertEqual(
                config_lib.Config.from_disk(services.CONFIG_PATH), self.config
            )

    def test_set_invalid_config(self) -> None:
        with self.start_stop_session():
            self.config["torrent_default_storage_mode"] = "invalid"
            with self.assertRaises(config_lib.InvalidConfigError):
                services.set_config(self.config)
            self.assertNotEqual(
                services.get_config().get_str("torrent_default_storage_mode"),
                "invalid",
            )

    def test_save_and_load_resume_data(self) -> None:
        with self.start_stop_session():
            services.get_session().add_torrent(tdummy.DEFAULT.atp())

        self.assertEqual(
            len(
                list(
                    resume_lib.iter_resume_data_from_disk(
                        services.RESUME_DATA_PATH
                    )
                )
            ),
            1,
        )

        with self.start_stop_session():
            self.assertEqual(len(services.get_session().get_torrents()), 1)

    def test_process_lock(self) -> None:
        with self.start_stop_session():
            with self.assertRaises(AssertionError):
                services.startup()


class TestDefaultATP(TemporaryDirectoryTestCase):
    def setUp(self) -> None:
        super().setUp()
        services.startup()

    def tearDown(self) -> None:
        services.shutdown()
        super().tearDown()

    def test_config_defaults(self) -> None:
        save_path = str(pathlib.Path("download").resolve())
        self.assertEqual(
            services.get_config()["torrent_default_save_path"], save_path
        )

        atp = services.get_default_atp()

        self.assertEqual(atp.save_path, save_path)
        self.assertEqual(atp.flags, lt.torrent_flags.default_flags)
        self.assertEqual(
            atp.storage_mode, lt.add_torrent_params().storage_mode
        )

    def test_set_non_defaults(self) -> None:
        # Set all non-default configs
        config = config_lib.Config(
            torrent_default_save_path=self.tempdir.name,
            torrent_default_flags_apply_ip_filter=False,
            torrent_default_storage_mode="allocate",
        )
        services.set_config(config)

        atp = services.get_default_atp()

        self.assertEqual(atp.save_path, self.tempdir.name)
        self.assertEqual(
            atp.flags,
            lt.torrent_flags.default_flags & ~lt.torrent_flags.apply_ip_filter,
        )
        self.assertEqual(
            atp.storage_mode, lt.storage_mode_t.storage_mode_allocate
        )

    def test_save_path_loop(self) -> None:
        bad_link = pathlib.Path("bad_link")
        bad_link.symlink_to(bad_link, target_is_directory=True)

        config = config_lib.Config(torrent_default_save_path=str(bad_link))
        with self.assertRaises(config_lib.InvalidConfigError):
            services.set_config(config)

    def test_flags_apply_ip_filter_null(self) -> None:
        config = config_lib.Config(torrent_default_flags_apply_ip_filter=None)
        with self.assertRaises(config_lib.InvalidConfigError):
            services.set_config(config)

    def test_storage_mode_invalid(self) -> None:
        config = config_lib.Config(torrent_default_storage_mode="invalid")
        with self.assertRaises(config_lib.InvalidConfigError):
            services.set_config(config)
