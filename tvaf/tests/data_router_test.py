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

import fastapi.testclient

from tvaf import app as app_lib
from tvaf import services

from . import lib


class FormatTest(lib.TestCase):
    def setUp(self) -> None:
        self.client = fastapi.testclient.TestClient(app_lib.APP)
        self.tempdir = tempfile.TemporaryDirectory()
        self.cwd = pathlib.Path.cwd()
        os.chdir(self.tempdir.name)
        services.startup()

    def tearDown(self) -> None:
        os.chdir(self.cwd)
        services.shutdown()

    def test_invalid_multihash(self) -> None:
        # not a valid multihash
        r = self.client.get("/v1/btmh/1234abcd/i/0")
        self.assertEqual(r.status_code, 422)
        self.assert_golden_json(r.json(), suffix="invalid_multihash.json")

        # wrong sha1 length
        r = self.client.get("/v1/btmh/1114a0/i/0")
        self.assertEqual(r.status_code, 422)
        self.assert_golden_json(r.json(), suffix="short_sha1.json")

        # odd-numbered hex digits
        r = self.client.get("/v1/btmh/a/i/0")
        self.assertEqual(r.status_code, 422)
        self.assert_golden_json(r.json(), suffix="odd_hex_digits.json")

        # not hexadecimal
        r = self.client.get("/v1/btmh/not-hexadecimal/i/0")
        self.assertEqual(r.status_code, 422)
        self.assert_golden_json(r.json(), suffix="not_hexadecimal.json")

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
