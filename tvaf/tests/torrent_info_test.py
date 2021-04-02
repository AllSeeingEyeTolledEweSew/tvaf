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

from typing import Any
from typing import cast
from typing import Dict
import unittest.mock

import libtorrent as lt
import multihash

from tvaf import lifecycle
from tvaf import plugins
from tvaf import services
from tvaf import torrent_info

from . import lib
from . import tdummy


class TorrentInfoTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config_patch = unittest.mock.patch.object(
            services, "get_config", return_value=lib.create_isolated_config()
        )
        self.config_patch.start()
        self.tdummy = tdummy.DEFAULT
        self.btmh = self.tdummy.btmh
        self.btmh_does_not_exist = multihash.Multihash(
            multihash.Func.sha1, b"a" * 20
        )
        self.btmh_not_sha1 = multihash.Multihash(
            multihash.Func.sha2_256, b"a" * 32
        )
        self.handle = services.get_session().add_torrent(self.tdummy.atp())

    def tearDown(self) -> None:
        lifecycle.clear()
        self.config_patch.stop()


class GetNumFilesTest(TorrentInfoTest):
    def test_accurate(self) -> None:
        self.assertEqual(
            torrent_info.get_num_files(self.btmh), len(self.tdummy.files)
        )

    def test_does_not_exist(self) -> None:
        with self.assertRaises(plugins.Pass):
            torrent_info.get_num_files(self.btmh_does_not_exist)

    def test_not_sha1(self) -> None:
        with self.assertRaises(plugins.Pass):
            torrent_info.get_num_files(self.btmh_not_sha1)


class CheckFileIndexTest(TorrentInfoTest):
    def test_success(self) -> None:
        torrent_info.check_file_index(self.btmh, 0)

    def test_failure(self) -> None:
        with self.assertRaises(IndexError):
            torrent_info.check_file_index(self.btmh, 1)
        with self.assertRaises(IndexError):
            torrent_info.check_file_index(self.btmh, -1)

    def test_does_not_exist(self) -> None:
        with self.assertRaises(plugins.Pass):
            torrent_info.check_file_index(self.btmh_does_not_exist, 0)

    def test_not_sha1(self) -> None:
        with self.assertRaises(plugins.Pass):
            torrent_info.check_file_index(self.btmh_not_sha1, 0)


class GetFileBoundsTest(TorrentInfoTest):
    def test_accurate(self) -> None:
        self.assertEqual(
            torrent_info.get_file_bounds(self.btmh, 0),
            (0, self.tdummy.files[0].length),
        )

    def test_bad_index(self) -> None:
        with self.assertRaises(IndexError):
            torrent_info.get_file_bounds(self.btmh, 1)

        with self.assertRaises(IndexError):
            torrent_info.get_file_bounds(self.btmh, -1)

    def test_does_not_exist(self) -> None:
        with self.assertRaises(plugins.Pass):
            torrent_info.get_file_bounds(self.btmh_does_not_exist, 0)

    def test_not_sha1(self) -> None:
        with self.assertRaises(plugins.Pass):
            torrent_info.get_file_bounds(self.btmh_not_sha1, 0)


class GetFileNameAndPathTest(TorrentInfoTest):
    def test_basic(self) -> None:
        self.assertEqual(
            torrent_info.get_file_path(self.btmh, 0), [b"test.txt"]
        )
        self.assertEqual(torrent_info.get_file_name(self.btmh, 0), b"test.txt")

    def test_bad_index(self) -> None:
        with self.assertRaises(IndexError):
            torrent_info.get_file_path(self.btmh, 1)
        with self.assertRaises(IndexError):
            torrent_info.get_file_path(self.btmh, -1)

        with self.assertRaises(IndexError):
            torrent_info.get_file_name(self.btmh, 1)
        with self.assertRaises(IndexError):
            torrent_info.get_file_name(self.btmh, -1)

    def test_does_not_exist(self) -> None:
        with self.assertRaises(plugins.Pass):
            torrent_info.get_file_path(self.btmh_does_not_exist, 0)
        with self.assertRaises(plugins.Pass):
            torrent_info.get_file_name(self.btmh_does_not_exist, 0)

    def test_not_sha1(self) -> None:
        with self.assertRaises(plugins.Pass):
            torrent_info.get_file_path(self.btmh_not_sha1, 0)
        with self.assertRaises(plugins.Pass):
            torrent_info.get_file_name(self.btmh_not_sha1, 0)

    def add(self, info: Dict[bytes, Any]) -> multihash.Multihash:
        atp = lt.add_torrent_params()
        atp.ti = lt.torrent_info({b"info": info})
        btmh = multihash.Multihash(
            multihash.Func.sha1, atp.ti.info_hash().to_bytes()
        )
        services.get_session().add_torrent(atp)
        return btmh

    def test_utf8_single(self) -> None:
        btmh = self.add(
            {
                b"name": b"test.txt",
                b"name.utf-8": b"test.txt",
                b"piece length": 16384,
                b"pieces": b"a" * 20,
                b"length": 1024,
            }
        )
        self.assertEqual(torrent_info.get_file_path(btmh, 0), ["test.txt"])
        self.assertEqual(torrent_info.get_file_name(btmh, 0), "test.txt")

    def test_utf8_multi(self) -> None:
        btmh = self.add(
            {
                b"name": b"a",
                b"name.utf-8": b"a",
                b"piece length": 16384,
                b"pieces": b"a" * 20,
                b"files": [
                    {
                        b"length": 1024,
                        b"path": [b"b", b"1.txt"],
                        b"path.utf-8": [b"b", b"1.txt"],
                    },
                    {
                        b"length": 1024,
                        b"path": [b"c", b"2.txt"],
                        b"path.utf-8": [b"c", b"2.txt"],
                    },
                ],
            }
        )
        self.assertEqual(
            torrent_info.get_file_path(btmh, 0), ["a", "b", "1.txt"]
        )
        self.assertEqual(torrent_info.get_file_name(btmh, 0), "1.txt")
        self.assertEqual(
            torrent_info.get_file_path(btmh, 1), ["a", "c", "2.txt"]
        )
        self.assertEqual(torrent_info.get_file_name(btmh, 1), "2.txt")

    def test_utf8_mixed(self) -> None:
        btmh = self.add(
            {
                b"name": b"a",
                b"name.utf-8": b"a",
                b"piece length": 16384,
                b"pieces": b"a" * 20,
                b"files": [
                    {
                        b"length": 1024,
                        b"path": [b"b", b"1.txt"],
                    },
                    {
                        b"length": 1024,
                        b"path": [b"c", b"2.txt"],
                    },
                ],
            }
        )
        self.assertEqual(
            torrent_info.get_file_path(btmh, 0), ["a", b"b", b"1.txt"]
        )
        self.assertEqual(torrent_info.get_file_name(btmh, 0), b"1.txt")
        btmh = self.add(
            {
                b"name": b"a",
                b"piece length": 16384,
                b"pieces": b"a" * 20,
                b"files": [
                    {
                        b"length": 1024,
                        b"path": [b"b", b"1.txt"],
                        b"path.utf-8": [b"b", b"1.txt"],
                    },
                    {
                        b"length": 1024,
                        b"path": [b"c", b"2.txt"],
                    },
                ],
            }
        )
        self.assertEqual(
            torrent_info.get_file_path(btmh, 0), [b"a", "b", "1.txt"]
        )
        self.assertEqual(torrent_info.get_file_name(btmh, 0), "1.txt")


class GetBencodedAndParsedInfoTest(TorrentInfoTest):
    def test_accurate(self) -> None:
        expected_info = dict(self.tdummy.info)
        expected_info.pop(b"pieces", None)
        got_info = torrent_info.get_parsed_info(self.btmh)
        got_info.pop(b"pieces", None)
        self.assertEqual(got_info, expected_info)

        got_info = cast(
            Dict[bytes, Any],
            lt.bdecode(torrent_info.get_bencoded_info(self.btmh)),
        )
        got_info.pop(b"pieces", None)
        self.assertEqual(got_info, expected_info)

    def test_does_not_exist(self) -> None:
        with self.assertRaises(plugins.Pass):
            torrent_info.get_parsed_info(self.btmh_does_not_exist)
        with self.assertRaises(plugins.Pass):
            torrent_info.get_bencoded_info(self.btmh_does_not_exist)

    def test_not_sha1(self) -> None:
        with self.assertRaises(plugins.Pass):
            torrent_info.get_parsed_info(self.btmh_not_sha1)
        with self.assertRaises(plugins.Pass):
            torrent_info.get_bencoded_info(self.btmh_not_sha1)
