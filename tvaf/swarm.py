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

from typing import Awaitable
from typing import Callable

import libtorrent as lt

from . import multihash
from . import torrent_info


async def _is_known_private(btmh: multihash.Multihash) -> bool:
    try:
        return await torrent_info.get_is_private_from_cache(btmh)
    except KeyError:
        return False


async def _configure_noop(atp: lt.add_torrent_params) -> None:
    pass


async def _get_configure_public(
    btmh: multihash.Multihash,
) -> Callable[[lt.add_torrent_params], Awaitable[None]]:
    if await _is_known_private(btmh):
        raise KeyError(btmh)

    return _configure_noop
