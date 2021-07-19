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


import datetime

from tvaf import concurrency
from tvaf import ltpy
from tvaf import services

from . import lib


class FormatTest(lib.AppTest, lib.TestCase):
    async def test_invalid_multihash(self) -> None:
        # not a valid multihash
        r = await self.client.get("/v1/session/btmh/ffff")
        self.assertEqual(r.status_code, 422)
        self.assert_golden_json(r.json(), suffix="invalid_multihash.json")

        # inconsistent sha1 length
        r = await self.client.get("/v1/session/btmh/1114a0")
        self.assertEqual(r.status_code, 422)
        self.assert_golden_json(r.json(), suffix="short_sha1.json")

        # wrong sha1 length (110100) -- should this be 422?

        # odd-numbered hex digits
        r = await self.client.get("/v1/session/btmh/a")
        self.assertEqual(r.status_code, 422)
        self.assert_golden_json(r.json(), suffix="odd_hex_digits.json")

        # not hexadecimal
        r = await self.client.get("/v1/session/btmh/not-hexadecimal")
        self.assertEqual(r.status_code, 422)
        self.assert_golden_json(r.json(), suffix="not_hexadecimal.json")

        # not sha1
        r = await self.client.get("/v1/session/btmh/1201cd")
        self.assertEqual(r.status_code, 404)
        self.assert_golden_json(r.json(), suffix="not_sha1.json")


class StatusTest(lib.AppTestWithTorrent, lib.TestCase):
    async def test_get(self) -> None:
        r = await self.client.get(f"/v1/session/btmh/{self.torrent.btmh}")
        self.assertEqual(r.status_code, 200)
        self.assert_golden_json(dict(r.headers), suffix="headers.json")

        status_dict = r.json()
        # test unstable parts
        self.assertIsInstance(status_dict.pop("added_time"), int)
        self.assertIsInstance(status_dict.pop("completed_time"), int)
        datetime.datetime.fromisoformat(status_dict.pop("last_download"))
        self.assertEqual(status_dict.pop("save_path"), self.tempdir.name)
        self.assert_golden_json(status_dict, suffix="body.json")


class GetPiecePrioritiesTest(lib.AppTestWithTorrent, lib.TestCase):
    async def test_get(self) -> None:
        r = await self.client.get(
            f"/v1/session/btmh/{self.torrent.btmh}/piece_priorities"
        )
        self.assertEqual(r.status_code, 200)
        self.assert_golden_json(dict(r.headers), suffix="headers.json")
        self.assert_golden_json(r.json(), suffix="body.json")


class RemoveTest(lib.AppTestWithTorrent, lib.TestCase):
    async def test_delete(self) -> None:
        r = await self.client.delete(f"/v1/session/btmh/{self.torrent.btmh}")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(
            await concurrency.to_thread(
                ltpy.handle_in_session,
                self.handle,
                await services.get_session(),
            )
        )
