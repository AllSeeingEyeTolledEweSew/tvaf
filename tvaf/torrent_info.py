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

from typing import Awaitable
from typing import Callable
from typing import Tuple

import libtorrent as lt

from . import lifecycle
from . import multihash


@lifecycle.alru_cache(maxsize=256)
async def get_file_bounds_from_cache(
    btmh: multihash.Multihash, file_index: int
) -> Tuple[int, int]:
    # TODO
    raise KeyError(btmh)


async def get_configure_atp(
    btmh: multihash.Multihash,
) -> Callable[[lt.add_torrent_params], Awaitable]:
    # TODO
    if btmh.func != multihash.Func.sha1:
        raise KeyError(btmh)

    async def configure_public(atp: lt.add_torrent_params) -> None:
        atp.info_hash = lt.sha1_hash(btmh.digest)

    return configure_public
