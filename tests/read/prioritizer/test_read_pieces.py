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

import pathlib
import random

import libtorrent as lt
import pytest

from tvaf import config as config_lib
from tvaf import ltpy
from tvaf import session as session_lib
import tvaf._internal.read as read_lib

PIECE_SIZE = 16384
NUM_PIECES = 1024


def generate_ti(pieces: int) -> lt.torrent_info:
    fs = lt.file_storage()
    fs.add_file("test.txt", pieces * PIECE_SIZE)
    ct = lt.create_torrent(fs, piece_size=PIECE_SIZE)
    for piece in range(pieces):
        ct.set_hash(piece, random.randbytes(20))
    return lt.torrent_info(ct.generate())


@pytest.fixture
def ti() -> lt.torrent_info:
    return generate_ti(NUM_PIECES)


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


def test_contract(handle: lt.torrent_handle) -> None:
    prioritizer = read_lib.ReadPrioritizer(handle)
    desired_pieces = list(range(10, NUM_PIECES - 10))
    with prioritizer.read_pieces(desired_pieces) as iterator:
        got_pieces = list(iterator)
    assert got_pieces == desired_pieces


def test_remove_before_read(handle: lt.torrent_handle, session: lt.session) -> None:
    prioritizer = read_lib.ReadPrioritizer(handle)
    desired_pieces = list(range(10, NUM_PIECES - 10))
    session.remove_torrent(handle)
    while handle.is_valid():
        pass
    with pytest.raises(ltpy.InvalidTorrentHandleError):
        with prioritizer.read_pieces(desired_pieces) as iterator:
            next(iterator)


def test_remove_during_read(handle: lt.torrent_handle, session: lt.session) -> None:
    prioritizer = read_lib.ReadPrioritizer(handle)
    desired_pieces = list(range(10, NUM_PIECES - 10))
    # TODO: if I scope pytest.raises() within read_pieces(), it fails. Why?
    with pytest.raises(ltpy.InvalidTorrentHandleError):
        with prioritizer.read_pieces(desired_pieces) as iterator:
            next(iterator)
            session.remove_torrent(handle)
            while handle.is_valid():
                pass
            next(iterator)


def test_set_priorities(handle: lt.torrent_handle) -> None:
    # TODO: test piece deadlines when we can
    initial_priorities = handle.get_piece_priorities()
    assert all(p > 0 and p < 7 for p in initial_priorities)
    prioritizer = read_lib.ReadPrioritizer(handle)
    desired_pieces = list(range(10, NUM_PIECES - 10))
    with prioritizer.read_pieces(desired_pieces) as iterator:
        # We shouldn't change priorities until the iterator is advanced
        assert handle.get_piece_priorities() == initial_priorities
        # When we advance the iterator, we expect the current piece to be realtime,
        # but not *all* pieces are realtime
        piece = next(iterator)
        priorities = handle.get_piece_priorities()
        assert priorities[piece] == 7
        assert any(p > 0 and p < 7 for p in priorities)
        # When we advance the iterator further, we expect the previous piece is no
        # longer realtime
        next(iterator)
        priorities = handle.get_piece_priorities()
        assert priorities[piece] < 7
    # After the context manager exits, no pieces should be realtime priority, even if
    # the iterator is not consumed
    priorities = handle.get_piece_priorities()
    assert all(p < 7 for p in priorities)


class _DummyError(Exception):
    pass


def test_reset_priorities_on_error(handle: lt.torrent_handle) -> None:
    prioritizer = read_lib.ReadPrioritizer(handle)
    desired_pieces = list(range(10, NUM_PIECES - 10))
    with pytest.raises(_DummyError):
        with prioritizer.read_pieces(desired_pieces) as iterator:
            next(iterator)
            raise _DummyError()
    # After the context manager exits, no pieces should be realtime priority
    priorities = handle.get_piece_priorities()
    assert all(p < 7 for p in priorities)
