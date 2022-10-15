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

from collections.abc import Iterator
from collections.abc import Sequence
import contextlib

import libtorrent as lt

from tvaf import ltpy


class TimeCriticalState:
    SEQ_BUFFER = 30

    def __init__(self, handle: lt.torrent_handle):
        self._handle = handle
        self._refcount: dict[int, int] = {}

    def _delta_reads(self, dec: set[int], inc: set[int]) -> None:
        # TODO: assign time critical pieces in reasonable order
        with ltpy.translate_exceptions():
            for piece in inc - dec:
                current = self._refcount.get(piece, 0)
                if current == 0:
                    self._handle.set_piece_deadline(piece, 0)
                self._refcount[piece] = current + 1
            for piece in dec - inc:
                current = self._refcount[piece]
                assert current > 0
                if current == 1:
                    self._handle.reset_piece_deadline(piece)
                    self._refcount.pop(piece)
                else:
                    self._refcount[piece] = current - 1

    @contextlib.contextmanager
    def time_critical_read(self, pieces: Sequence[int]) -> Iterator[Iterator[int]]:
        reset_on_exit = True
        prev_reading: set[int] = set()

        def iterator() -> Iterator[int]:
            nonlocal prev_reading
            for i, piece in enumerate(pieces):
                reading = set(pieces[i : i + self.SEQ_BUFFER])
                self._delta_reads(prev_reading, reading)
                prev_reading = reading
                yield piece

        try:
            yield iterator()
        except ltpy.InvalidTorrentHandleError:
            reset_on_exit = False
            raise
        finally:
            if reset_on_exit:
                self._delta_reads(prev_reading, set())
