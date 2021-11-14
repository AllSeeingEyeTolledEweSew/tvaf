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

import random
from typing import Tuple

from later.unittest.backport import async_case
import libtorrent as lt

from tvaf import lifecycle
from tvaf import torrent_info

from . import lib


class TestWithPlugins(async_case.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.fake_eps = lib.EntryPointFaker()
        self.fake_eps.enable()

    async def asyncTearDown(self) -> None:
        await super().asyncTearDown()
        self.fake_eps.disable()
        lifecycle.clear()


INFO_HASHES = lt.info_hash_t(
    lt.sha1_hash(bytes(random.getrandbits(8) for _ in range(20)))
)
INDEX = 123
BOUNDS = (1234, 5678)


async def btih_to_keyerror(info_hashes: lt.info_hash_t) -> None:
    assert info_hashes == INFO_HASHES
    raise KeyError(info_hashes)


async def btih_to_true(info_hashes: lt.info_hash_t) -> bool:
    assert info_hashes == INFO_HASHES
    return True


async def btih_index_to_keyerror(info_hashes: lt.info_hash_t, index: int) -> None:
    assert info_hashes == INFO_HASHES
    assert index == INDEX
    raise KeyError(info_hashes)


async def btih_index_to_bounds(
    info_hashes: lt.info_hash_t, index: int
) -> Tuple[int, int]:
    assert info_hashes == INFO_HASHES
    assert index == INDEX
    return BOUNDS


class TestIsPrivate(TestWithPlugins):
    async def test_no_plugins(self) -> None:
        with self.assertRaises(KeyError):
            await torrent_info.is_private(INFO_HASHES)

    async def test_keyerror(self) -> None:
        self.fake_eps.add("keyerror", btih_to_keyerror, "tvaf.torrent_info.is_private")
        with self.assertRaises(KeyError):
            await torrent_info.is_private(INFO_HASHES)

    async def test_true(self) -> None:
        self.fake_eps.add("true", btih_to_true, "tvaf.torrent_info.is_private")
        self.assertTrue(await torrent_info.is_private(INFO_HASHES))

    async def test_keyerror_and_true(self) -> None:
        self.fake_eps.add("keyerror", btih_to_keyerror, "tvaf.torrent_info.is_private")
        self.fake_eps.add("true", btih_to_true, "tvaf.torrent_info.is_private")
        self.assertTrue(await torrent_info.is_private(INFO_HASHES))


class TestFileBoundsFromCache(TestWithPlugins):
    async def test_no_plugins(self) -> None:
        with self.assertRaises(KeyError):
            await torrent_info.map_file(INFO_HASHES, INDEX)

    async def test_keyerror(self) -> None:
        self.fake_eps.add(
            "keyerror",
            btih_index_to_keyerror,
            "tvaf.torrent_info.map_file",
        )
        with self.assertRaises(KeyError):
            await torrent_info.map_file(INFO_HASHES, INDEX)

    async def test_valid(self) -> None:
        self.fake_eps.add(
            "valid",
            btih_index_to_bounds,
            "tvaf.torrent_info.map_file",
        )
        self.assertEqual(
            await torrent_info.map_file(INFO_HASHES, INDEX),
            BOUNDS,
        )

    async def test_keyerror_and_valid(self) -> None:
        self.fake_eps.add(
            "keyerror",
            btih_index_to_keyerror,
            "tvaf.torrent_info.map_file",
        )
        self.fake_eps.add(
            "valid",
            btih_index_to_bounds,
            "tvaf.torrent_info.map_file",
        )
        self.assertEqual(
            await torrent_info.map_file(INFO_HASHES, INDEX),
            BOUNDS,
        )
