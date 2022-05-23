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

import dataclasses
import random
from typing import Any
from typing import cast

import libtorrent as lt
import pytest

from tests import epfake
from tvaf import torrent_info


@pytest.fixture
def info_hashes() -> lt.info_hash_t:
    return lt.info_hash_t(lt.sha1_hash(bytes(random.getrandbits(8) for _ in range(20))))


@pytest.fixture
def index() -> int:
    return random.randrange(0, 10000)


@pytest.fixture
def bounds() -> tuple[int, int]:
    size = random.randrange(0, 10000)
    base = random.randrange(0, 10000)
    return (base, base + size)


@dataclasses.dataclass
class Env:
    raise_keyerror: bool = False
    return_bounds: bool = False


@pytest.fixture
def env(
    info_hashes: lt.info_hash_t,
    index: int,
    bounds: tuple[int, int],
    entry_point_faker: epfake.EntryPointFaker,
    request: Any,
) -> Env:
    value = cast(Env, request.param)
    if value.raise_keyerror:

        async def _raise_keyerror(ih: lt.info_hash_t, i: int) -> None:
            assert ih == info_hashes
            assert i == index
            raise KeyError(ih)

        entry_point_faker.add("keyerror", _raise_keyerror, "tvaf.torrent_info.map_file")
    if value.return_bounds:

        async def _return_bounds(ih: lt.info_hash_t, i: int) -> tuple[int, int]:
            assert ih == info_hashes
            assert i == index
            return bounds

        entry_point_faker.add("true", _return_bounds, "tvaf.torrent_info.map_file")
    return value


ENVS = (
    pytest.param(Env(), marks=pytest.mark.xfail(raises=KeyError), id="no plugins"),
    pytest.param(
        Env(raise_keyerror=True),
        marks=pytest.mark.xfail(raises=KeyError),
        id="non-authoritative",
    ),
    pytest.param(Env(return_bounds=True), id="valid bounds"),
    pytest.param(
        Env(return_bounds=True, raise_keyerror=True), id="override with bounds"
    ),
)


@pytest.mark.parametrize("env", ENVS, indirect=True)
async def test_map_file(
    env: Env, info_hashes: lt.info_hash_t, index: int, bounds: tuple[int, int]
) -> None:
    assert (await torrent_info.map_file(info_hashes, index)) == bounds
