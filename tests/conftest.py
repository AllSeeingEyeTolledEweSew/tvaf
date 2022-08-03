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

import enum
import functools
import random
from typing import Any
from typing import Callable
from typing import Coroutine
from typing import Iterator
from typing import Protocol
from typing import TypeVar

import anyio
import libtorrent as lt
import pytest
from typing_extensions import ParamSpec

from tests import epfake
from tvaf import caches as caches_lib


@pytest.fixture
def caches() -> Iterator:
    yield
    caches_lib.clear_all()


@pytest.fixture
def entry_point_faker() -> Iterator[epfake.EntryPointFaker]:
    faker = epfake.EntryPointFaker()
    faker.enable()
    yield faker
    faker.disable()


class Proto(enum.IntFlag):
    V1 = 1
    V2 = 2
    HYBRID = 3


V1 = Proto.V1
V2 = Proto.V2
HYBRID = Proto.HYBRID


class MkAtp(Protocol):
    def __call__(self, *, proto: Proto = ...) -> lt.add_torrent_params:
        ...


def _mkatp(
    tmp_path_factory: pytest.TempPathFactory, *, proto=Proto.HYBRID
) -> lt.add_torrent_params:
    atp = lt.add_torrent_params()
    # As of 2.0.6, create_torrent.set_hash2 isn't bound in python
    tmp_path = tmp_path_factory.mktemp("test-atp")
    (tmp_path / "file.txt").write_bytes(random.randbytes(1024))
    fs = lt.file_storage()
    lt.add_files(fs, str(tmp_path))
    flags = 0
    if not (proto & V2):
        flags = lt.create_torrent.v1_only
    elif not (proto & V1):
        flags = lt.create_torrent.v2_only
    ct = lt.create_torrent(fs, flags=flags)
    lt.set_piece_hashes(ct, str(tmp_path.parent))
    atp.ti = lt.torrent_info(ct.generate())
    return atp


@pytest.fixture
def mkatp(
    tmp_path_factory: pytest.TempPathFactory,
) -> MkAtp:
    return functools.partial(_mkatp, tmp_path_factory)


_T = TypeVar("_T")
_P = ParamSpec("_P")


def timeout(
    delay: float,
) -> Callable[
    [Callable[_P, Coroutine[Any, Any, _T]]], Callable[_P, Coroutine[Any, Any, _T]]
]:
    def wrapper(
        func: Callable[_P, Coroutine[Any, Any, _T]]
    ) -> Callable[_P, Coroutine[Any, Any, _T]]:
        @functools.wraps(func)
        async def run(*args: _P.args, **kwargs: _P.kwargs) -> _T:
            with anyio.fail_after(delay):
                return await func(*args, **kwargs)

        return run

    return wrapper
