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

import asyncio
from collections.abc import Sequence
import hashlib
import itertools
import pathlib
import random
from typing import Callable
from typing import cast

import anyio
import asyncstdlib
import libtorrent as lt
import pytest

from tests import lib
from tvaf import config as config_lib
from tvaf import ltpy
from tvaf import session as session_lib
from tvaf._internal import wait_pieces as wait_pieces_lib

PIECE_SIZE = 16384
NUM_PIECES = 1024


@pytest.fixture
def piece_data() -> list[bytes]:
    return [random.randbytes(PIECE_SIZE) for _ in range(NUM_PIECES)]


@pytest.fixture
def ti(piece_data: list[bytes]) -> lt.torrent_info:
    fs = lt.file_storage()
    fs.add_file("test.txt", NUM_PIECES * PIECE_SIZE)
    ct = lt.create_torrent(fs, piece_size=PIECE_SIZE)
    for piece, data in enumerate(piece_data):
        ct.set_hash(piece, hashlib.sha1(data).digest())
    return lt.torrent_info(ct.generate())


@pytest.fixture
def session(config: config_lib.Config) -> lt.session:
    return session_lib.SessionService(config=config).session


@pytest.fixture
def atp(ti: lt.torrent_info, tmp_path: pathlib.Path) -> lt.add_torrent_params:
    local_atp = lt.add_torrent_params()
    local_atp.save_path = str(tmp_path)
    local_atp.ti = ti
    return local_atp


@pytest.fixture
def handle(atp: lt.add_torrent_params, session: lt.session) -> lt.torrent_handle:
    return session.add_torrent(atp)


FeedPiece = Callable[[int], None]


@pytest.fixture
async def feed_piece(handle: lt.torrent_handle, piece_data: list[bytes]) -> FeedPiece:
    await lib.wait_done_checking_or_error(handle)

    def do_feed_piece(piece: int) -> None:
        handle.add_piece(piece, piece_data[piece], 0)

    return do_feed_piece


@pytest.fixture(params=list(itertools.permutations((0, 1, 2))))
def desired_pieces(request: pytest.FixtureRequest) -> Sequence[int]:
    return cast(Sequence[int], request.param)


@pytest.fixture(params=list(itertools.permutations((0, 1, 2))))
def completed_pieces(request: pytest.FixtureRequest) -> Sequence[int]:
    return cast(Sequence[int], request.param)


async def test_prior_received(
    handle: lt.torrent_handle, feed_piece: FeedPiece, desired_pieces: Sequence[int]
) -> None:
    for piece in desired_pieces:
        feed_piece(piece)
    async with wait_pieces_lib.wait_pieces(
        handle, desired_pieces, poll_interval=0.1
    ) as iterator:
        got = await asyncstdlib.tuple(iterator)
    assert got == desired_pieces


async def test_concurrent_receive(
    handle: lt.torrent_handle,
    feed_piece: FeedPiece,
    desired_pieces: Sequence[int],
    completed_pieces: Sequence[int],
) -> None:
    async with wait_pieces_lib.wait_pieces(
        handle, desired_pieces, poll_interval=0.1
    ) as iterator:
        for piece in completed_pieces:
            feed_piece(piece)
        got = await asyncstdlib.tuple(iterator)
    assert got == desired_pieces


async def test_no_premature_output(
    handle: lt.torrent_handle,
    feed_piece: FeedPiece,
    desired_pieces: Sequence[int],
    completed_pieces: Sequence[int],
) -> None:
    with pytest.raises(TimeoutError):
        with anyio.fail_after(0.3):
            async with wait_pieces_lib.wait_pieces(
                handle, desired_pieces, poll_interval=0.1
            ) as iterator:
                for piece in completed_pieces:
                    feed_piece(piece + 1)
                async for piece in iterator:
                    pass


async def test_bad_piece_index(handle: lt.torrent_handle) -> None:
    with pytest.raises(IndexError):
        async with wait_pieces_lib.wait_pieces(
            handle, [NUM_PIECES], poll_interval=0.1
        ) as iterator:
            async for piece in iterator:
                pass
    with pytest.raises(IndexError):
        async with wait_pieces_lib.wait_pieces(
            handle, [-1], poll_interval=0.1
        ) as iterator:
            async for piece in iterator:
                pass


async def test_remove_before_read(
    handle: lt.torrent_handle, session: lt.session
) -> None:
    session.remove_torrent(handle)
    while handle.is_valid():
        await asyncio.sleep(0)
    with pytest.raises(ltpy.InvalidTorrentHandleError):
        async with wait_pieces_lib.wait_pieces(
            handle, [0], poll_interval=0.1
        ) as iterator:
            await iterator.__anext__()


async def test_remove_during_read(
    handle: lt.torrent_handle, session: lt.session, feed_piece: FeedPiece
) -> None:
    feed_piece(0)
    # TODO: if I scope pytest.raises() within read_pieces(), it fails. Why?
    with pytest.raises(ltpy.InvalidTorrentHandleError):
        async with wait_pieces_lib.wait_pieces(
            handle, [0, 1], poll_interval=0.1
        ) as iterator:
            await iterator.__anext__()
            session.remove_torrent(handle)
            while handle.is_valid():
                await asyncio.sleep(0)
            await iterator.__anext__()


class DummyError(Exception):
    pass


async def test_raise_error(handle: lt.torrent_handle, feed_piece: FeedPiece) -> None:
    feed_piece(0)
    with pytest.raises(DummyError):
        async with wait_pieces_lib.wait_pieces(
            handle, [0], poll_interval=0.1
        ) as iterator:
            await iterator.__anext__()
            raise DummyError()
