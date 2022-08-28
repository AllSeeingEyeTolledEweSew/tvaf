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
import datetime
import unittest

from tvaf import ltpy
from tvaf import services

from . import lib


class FormatTest(lib.AppTest, lib.TestCase):
    async def test_invalid_info_hash(self) -> None:
        r = await self.client.get("/torrents/a")
        self.assertEqual(r.status_code, 422)
        self.assert_golden_json(r.json(), suffix="short.json")

        r = await self.client.get("/torrents/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
        self.assertEqual(r.status_code, 422)
        self.assert_golden_json(r.json(), suffix="long.json")

        r = await self.client.get("/torrents/zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz")
        self.assertEqual(r.status_code, 422)
        self.assert_golden_json(r.json(), suffix="not_hex.json")


class StatusTest(lib.AppTestWithTorrent, lib.TestCase):
    @unittest.skip("flaky")
    async def test_get(self) -> None:
        r = await self.client.get(f"/torrents/{self.torrent.sha1_hash}")
        self.assertEqual(r.status_code, 200)
        # some fields are unstable, so content-length is unstable
        headers = dict(r.headers)
        headers.pop("content-length")
        self.assert_golden_json(headers, suffix="headers.json")

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
            f"/torrents/{self.torrent.sha1_hash}/piece_priorities"
        )
        self.assertEqual(r.status_code, 200)
        self.assert_golden_json(dict(r.headers), suffix="headers.json")
        self.assert_golden_json(r.json(), suffix="body.json")


class RemoveTest(lib.AppTestWithTorrent, lib.TestCase):
    async def test_delete(self) -> None:
        r = await self.client.delete(f"/torrents/{self.torrent.sha1_hash}")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(
            await asyncio.to_thread(
                ltpy.handle_in_session,
                self.handle,
                await services.get_session(),
            )
        )


class TorrentListTest(lib.AppTestWithTorrent, lib.TestCase):
    @unittest.skip("flaky")
    async def test_torrent_list(self) -> None:
        r = await self.client.get("/torrents")
        self.assertEqual(r.status_code, 200)
        # some fields are unstable, so content-length is unstable
        headers = dict(r.headers)
        headers.pop("content-length")
        self.assert_golden_json(headers, suffix="headers.json")

        statuses = r.json()
        # test unstable parts
        self.assertIsInstance(statuses[0].pop("added_time"), int)
        self.assertIsInstance(statuses[0].pop("completed_time"), int)
        datetime.datetime.fromisoformat(statuses[0].pop("last_download"))
        self.assertEqual(statuses[0].pop("save_path"), self.tempdir.name)
        self.assert_golden_json(statuses, suffix="body.json")
