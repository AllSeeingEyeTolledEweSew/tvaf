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

"""Functions relating to swarm metadata.

A swarm is an administrative boundary. A swarm is defined as a set of peers
which *may* connect to each other to exchange data for a torrent.

For a public torrent (the "private" field is not set), there's only one swarm,
consisting of all peers. Peers are allowed to announce to the DHT, and may
connect to any peer discovered by any means.

For a private torrent hosted on a private tracker, the peers announcing on that
tracker are a swarm. These peers may *only* connect to other peers announcing
on the same tracker. Peers may not announce on any other trackers or the DHT,
or otherwise leak knowledge of the swarm outside the swarm.

If two private trackers host the same torrent, there are two swarms for that
torrent. The two swarms are not allowed to connect to each other.

Note that there is a one-to-many correspondence from swarms to tracker URLs.
For example, when a private tracker migrates their domain name, they may have
more than one valid announce URL, and peers may announce on both during the
transition.

Currently, libtorrent may only connect to one swarm at a time for a given
torrent. In the future, I hope to be able to connect to multiple swarms for
faster downloads, but this will require modifications to libtorrent, and design
input and opt-in from tracker administrators about how this would work.
"""

import asyncio
import contextlib
from typing import Awaitable
from typing import Callable
from typing import cast
from typing import Dict
from typing import Mapping

import libtorrent as lt

from . import plugins
from . import torrent_info

ConfigureSwarm = Callable[[lt.add_torrent_params], Awaitable]
"""Configures an add_torrent_params to connect to a swarm.

A caller must set the info_hashes attribute before calling a ConfigureSwarms
function. A ConfigureSwarm function may assume it is set, and use it as an
argument to configure the specific torrent.

A ConfigureSwarms should configure the add_torrent_params such that libtorrent
will connect to a given swarm and obey the rules of that swarm.

Therefore, a ConfigureSwarms function must either
 * do nothing, in the case of the public swarm (the preset info_hashes is
   sufficient to access the DHT), or
 * set the ti attribute and/or others, such that libtorrent knows the torrent
   is private, and configure tracker URLs.
"""

AccessSwarm = Callable[[lt.info_hash_t], Awaitable[ConfigureSwarm]]
"""Checks that a swarm can access the torrent, and returns a ConfigureSwarm.

If the swarm cannot access the torrent, it must raise KeyError.

An AccessSwarm function should do minimal work to determine if the swarm can
access the torrent. If the plugin needs to fetch a resource (a .torrent file)
to configure the torrent for access to the swarm, then this fetch should be
done in the returned ConfigureSwarm function, not in the AccessSwarm function.
"""


def get_name_to_access_swarm() -> Mapping[str, AccessSwarm]:
    """Retrieves all AccessSwarm functions from plugins.

    AccessSwarm functions are registered as entry points, as described above.

    Returns:
        A mapping from swarm name to AccessSwarm functions.
    """
    return cast(
        Mapping[str, AccessSwarm], plugins.get("tvaf.swarm.access_swarm")
    )


async def get_name_to_configure_swarm(
    info_hashes: lt.info_hash_t,
) -> Mapping[str, ConfigureSwarm]:
    """Retrieves all ConfigureSwarm functions from plugins.

    This calls all registered AccessSwarm functions, returning a mapping from
    swarm name to the resulting ConfigureSwarm functions.

    If any AccessSwarm function raises KeyError, it will not be included in the
    mapping.

    Returns:
        A mapping from swarm name to ConfigureSwarm functions.
    """
    # Runs all AccessSwarm functions in parallel
    name_to_task = {
        name: asyncio.create_task(access(info_hashes))
        for name, access in get_name_to_access_swarm().items()
    }
    name_to_configure_swarm: Dict[str, ConfigureSwarm] = {}
    try:
        for name, task in name_to_task.items():
            with contextlib.suppress(KeyError):
                name_to_configure_swarm[name] = await task
    finally:
        for task in name_to_task.values():
            task.cancel()
    return name_to_configure_swarm


async def _is_known_private(info_hashes: lt.info_hash_t) -> bool:
    try:
        return await torrent_info.is_private(info_hashes)
    except KeyError:
        return False


async def _configure_public(atp: lt.add_torrent_params) -> None:
    assert not atp.info_hashes.get_best().is_all_zeros()
    assert atp.ti is None or not atp.ti.priv()
    # TODO: check trackers against known swarms


async def _access_public(info_hashes: lt.info_hash_t) -> ConfigureSwarm:
    if await _is_known_private(info_hashes):
        raise KeyError(info_hashes)

    return _configure_public
