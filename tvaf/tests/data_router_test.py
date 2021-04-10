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
import os
import pathlib
import tempfile
import unittest

import fastapi.testclient
import libtorrent as lt

from tvaf import app as app_lib
from tvaf import services

from . import lib
from . import request_test_utils
from . import tdummy


class AppTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = fastapi.testclient.TestClient(app_lib.APP)
        self.tempdir = tempfile.TemporaryDirectory()
        self.cwd = pathlib.Path.cwd()
        os.chdir(self.tempdir.name)
        services.startup()

    def tearDown(self) -> None:
        os.chdir(self.cwd)
        services.shutdown()


class FormatTest(AppTest, lib.TestCase):
    def test_invalid_multihash(self) -> None:
        # not a valid multihash
        r = self.client.get("/v1/btmh/ffff/i/0")
        self.assertEqual(r.status_code, 422)
        self.assert_golden_json(r.json(), suffix="invalid_multihash.json")

        # inconsistent sha1 length
        r = self.client.get("/v1/btmh/1114a0/i/0")
        self.assertEqual(r.status_code, 422)
        self.assert_golden_json(r.json(), suffix="short_sha1.json")

        # wrong sha1 length (110100) -- should this be 422?

        # odd-numbered hex digits
        r = self.client.get("/v1/btmh/a/i/0")
        self.assertEqual(r.status_code, 422)
        self.assert_golden_json(r.json(), suffix="odd_hex_digits.json")

        # not hexadecimal
        r = self.client.get("/v1/btmh/not-hexadecimal/i/0")
        self.assertEqual(r.status_code, 422)
        self.assert_golden_json(r.json(), suffix="not_hexadecimal.json")

        # not sha1
        r = self.client.get("/v1/btmh/1201cd/i/0")
        self.assertEqual(r.status_code, 404)
        self.assert_golden_json(r.json(), suffix="not_sha1.json")

    def test_invalid_file_index(self) -> None:
        r = self.client.get(
            "/v1/btmh/1114aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/i/-1"
        )
        self.assertEqual(r.status_code, 422)
        self.assert_golden_json(r.json(), suffix="negative_index.json")

        r = self.client.get(
            "/v1/btmh/1114aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/i/a"
        )
        self.assertEqual(r.status_code, 422)
        self.assert_golden_json(r.json(), suffix="bad_index.json")

    def test_unknown_torrent(self) -> None:
        r = self.client.get(
            "/v1/btmh/1114aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/i/0"
        )
        self.assertEqual(r.status_code, 404)
        self.assert_golden_json(r.json())


class DataTest(AppTest, lib.TestCase):
    def setUp(self) -> None:
        super().setUp()

        self.torrent = tdummy.DEFAULT
        self.torrent.entry_point_faker.enable()

    def tearDown(self) -> None:
        super().tearDown()
        self.torrent.entry_point_faker.disable()

    def test_download_from_seed(self) -> None:
        seed = lib.create_isolated_session_service().session
        seed_dir = tempfile.TemporaryDirectory()
        atp = self.torrent.atp()
        atp.save_path = seed_dir.name
        atp.flags &= ~lt.torrent_flags.paused
        handle = seed.add_torrent(atp)
        # https://github.com/arvidn/libtorrent/issues/4980: add_piece() while
        # checking silently fails in libtorrent 1.2.8.
        request_test_utils.wait_done_checking_or_error(handle)
        for i, piece in enumerate(self.torrent.pieces):
            # NB: bug in libtorrent where add_piece accepts str but not bytes
            handle.add_piece(i, piece.decode(), 0)

        def add_seed_peer(atp: lt.add_torrent_params) -> None:
            atp.peers = [("127.0.0.1", seed.listen_port())]

        with lib.EntryPointFaker() as faker:
            faker.add("_test", add_seed_peer, "tvaf.services.configure_atp")

            r = self.client.get(f"/v1/btmh/{self.torrent.btmh}/i/0")
            self.assertTrue(r.ok)
            self.assertEqual(r.content, self.torrent.files[0].data)
            self.assert_golden_json(dict(r.headers), suffix="headers.json")
