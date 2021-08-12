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

from later.unittest.backport import async_case
import libtorrent as lt

from tvaf import lifecycle
from tvaf import multihash
from tvaf import swarm

from . import lib


class TestPublicSwarm(async_case.IsolatedAsyncioTestCase):
    async def test_public_swarm(self) -> None:
        # by default, the public swarm (and only the public swarm) should be
        # configured
        name_to_access_swarm = swarm.get_name_to_access_swarm()
        self.assertEqual(set(name_to_access_swarm.keys()), {"public"})

        # The public swarm should be accessible to an arbitrary torrent
        access = name_to_access_swarm["public"]
        configure_public_swarm = await access(BTMH)

        # The public ConfigureSwarm function should do nothing
        atp = lt.add_torrent_params()
        atp.info_hashes = lt.info_hash_t(lt.sha1_hash(BTMH.digest))
        before = lt.write_resume_data(atp)
        await configure_public_swarm(atp)
        after = lt.write_resume_data(atp)
        self.assertEqual(after, before)


BTMH = multihash.Multihash(
    multihash.Func.sha1, bytes(random.getrandbits(8) for _ in range(20))
)
TRACKER = "http://127.0.0.1:12345"


class TestWithPlugins(async_case.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        lifecycle.clear()
        self.fake_eps = lib.EntryPointFaker()
        self.fake_eps.enable()

    async def asyncTearDown(self) -> None:
        await super().asyncTearDown()
        self.fake_eps.disable()
        lifecycle.clear()


async def configure_all(atp: lt.add_torrent_params) -> None:
    assert atp.info_hashes == lt.info_hash_t(lt.sha1_hash(BTMH.digest))
    atp.trackers = [TRACKER]


async def access_all(btmh: multihash.Multihash) -> swarm.ConfigureSwarm:
    assert btmh == BTMH
    return configure_all


async def access_none(btmh: multihash.Multihash) -> swarm.ConfigureSwarm:
    raise KeyError(btmh)


class TestGetNameToAccessSwarm(TestWithPlugins):
    async def test_all_and_none(self) -> None:
        self.fake_eps.add("all", access_all, "tvaf.swarm.access_swarm")
        self.fake_eps.add("none", access_none, "tvaf.swarm.access_swarm")

        name_to_access_swarm = swarm.get_name_to_access_swarm()

        self.assertEqual(
            set(name_to_access_swarm.keys()), {"public", "all", "none"}
        )
        with self.assertRaises(KeyError):
            await name_to_access_swarm["none"](BTMH)
        configure_swarm = await name_to_access_swarm["all"](BTMH)

        atp = lt.add_torrent_params()
        atp.info_hashes = lt.info_hash_t(lt.sha1_hash(BTMH.digest))
        await configure_swarm(atp)
        self.assertEqual(atp.trackers, [TRACKER])


class TestGetNameToConfigureSwarm(TestWithPlugins):
    async def test_all_and_none(self) -> None:
        self.fake_eps.add("all", access_all, "tvaf.swarm.access_swarm")
        self.fake_eps.add("none", access_none, "tvaf.swarm.access_swarm")

        name_to_configure_swarm = await swarm.get_name_to_configure_swarm(BTMH)

        self.assertEqual(
            set(name_to_configure_swarm.keys()), {"public", "all"}
        )

        atp = lt.add_torrent_params()
        atp.info_hashes = lt.info_hash_t(lt.sha1_hash(BTMH.digest))
        await name_to_configure_swarm["all"](atp)
        self.assertEqual(atp.trackers, [TRACKER])
