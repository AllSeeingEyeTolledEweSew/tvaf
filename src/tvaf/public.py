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

"""Support for the public swarm."""
from __future__ import annotations

import contextlib
from typing import AsyncIterator

import libtorrent as lt

from . import config as config_lib
from . import services
from . import swarm
from . import torrent_info


async def _is_known_private(info_hashes: lt.info_hash_t) -> bool:
    try:
        return await torrent_info.is_private(info_hashes)
    except KeyError:
        return False


_enable = True


@services.stage_config_plugin("50_public")
@contextlib.asynccontextmanager
async def _stage_config(config: config_lib.Config) -> AsyncIterator:
    enable = config.get_bool("public_enable")
    if enable is None:
        enable = True
    yield
    global _enable
    _enable = enable


@swarm.access_swarm_plugin("public")
async def _access(info_hashes: lt.info_hash_t) -> swarm.ConfigureSwarm:
    if not _enable or await _is_known_private(info_hashes):
        raise KeyError(info_hashes)

    async def configure(atp: lt.add_torrent_params) -> None:
        assert not atp.info_hashes.get_best().is_all_zeros()
        assert atp.ti is None or not atp.ti.priv()
        # TODO: check trackers against known swarms

    return configure
