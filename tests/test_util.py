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

"""Tests for the tvaf.util module."""
from __future__ import annotations

import select
import selectors
import threading
import time
import unittest

from tvaf import util


class TestBitmapIsSet(unittest.TestCase):
    """Tests for tvaf.util.bitmap_is_set()."""

    def test_positive(self) -> None:
        self.assertTrue(util.bitmap_is_set(b"\x00\x08", 12))

    def test_negative(self) -> None:
        self.assertFalse(util.bitmap_is_set(b"\x00\x08", 13))


class TestIterBitmap(unittest.TestCase):
    """Tests for tvaf.util.iter_bitmap()."""

    def test_full_range(self) -> None:
        self.assertSequenceEqual(
            list(util.iter_bitmap(b"\x00\x08", 0, 16)),
            [
                False,
                False,
                False,
                False,
                False,
                False,
                False,
                False,
                False,
                False,
                False,
                False,
                True,
                False,
                False,
                False,
            ],
        )

    def test_sub_range(self) -> None:
        self.assertSequenceEqual(
            list(util.iter_bitmap(b"\x00\x08", 12, 16)),
            [True, False, False, False],
        )


class TestRangeToPieces(unittest.TestCase):
    """Tests for tvaf.util.range_to_pieces()."""

    def test_empty_range(self) -> None:
        self.assertEqual(util.range_to_pieces(1024, 1000, 1000), (0, 0))

    def test_non_edge_cases(self) -> None:
        self.assertEqual(util.range_to_pieces(1024, 1000, 2000), (0, 2))

    def test_edge_cases(self) -> None:
        self.assertEqual(util.range_to_pieces(1024, 0, 2048), (0, 2))


class TestEnumPieceIsSet(unittest.TestCase):
    """Tests for tvaf.util.enum_piece_is_set()."""

    def test_empty(self) -> None:
        self.assertSequenceEqual(
            list(util.enum_piece_is_set(b"\x80", 1024, 1000, 1000)), []
        )

    def test_non_edge_cases(self) -> None:
        self.assertSequenceEqual(
            list(util.enum_piece_is_set(b"\x80", 1024, 1000, 2000)),
            [(0, True), (1, False)],
        )

    def test_edge_cases(self) -> None:
        self.assertSequenceEqual(
            list(util.enum_piece_is_set(b"\x80", 1024, 0, 2048)),
            [(0, True), (1, False)],
        )


class TestIterPieceIsSet(unittest.TestCase):
    """Tests for tvaf.util.iter_piece_is_set()."""

    def test_empty(self) -> None:
        self.assertSequenceEqual(
            list(util.iter_piece_is_set(b"\x80", 1024, 1000, 1000)), []
        )

    def test_non_edge_cases(self) -> None:
        self.assertSequenceEqual(
            list(util.iter_piece_is_set(b"\x80", 1024, 1000, 2000)),
            [True, False],
        )

    def test_edge_cases(self) -> None:
        self.assertSequenceEqual(
            list(util.iter_piece_is_set(b"\x80", 1024, 0, 2048)), [True, False]
        )


class TestEnumPiecewiseRanges(unittest.TestCase):
    """Tests for tvaf.util.enum_piecewise_ranges()."""

    def test_empty(self) -> None:
        self.assertSequenceEqual(list(util.enum_piecewise_ranges(1024, 1000, 1000)), [])

    def test_non_edge_cases(self) -> None:
        self.assertSequenceEqual(
            list(util.enum_piecewise_ranges(1024, 1000, 2000)),
            [(0, 1000, 1024), (1, 1024, 2000)],
        )

    def test_edge_cases(self) -> None:
        self.assertSequenceEqual(
            list(util.enum_piecewise_ranges(1024, 0, 2048)),
            [(0, 0, 1024), (1, 1024, 2048)],
        )


class TestSelectablePipe(unittest.TestCase):
    def test_select_write_before(self) -> None:
        rfile, wfile = util.selectable_pipe()
        wfile.write(b"\0")
        result = select.select((rfile,), (), ())
        self.assertEqual(result, ([rfile], [], []))
        rfile.close()
        wfile.close()

    def test_select_write_from_thread(self) -> None:
        rfile, wfile = util.selectable_pipe()

        def write_from_thread() -> None:
            # Is there a way to synchronize this?
            time.sleep(0.1)
            wfile.write(b"\0")

        threading.Thread(target=write_from_thread).start()
        result = select.select((rfile,), (), ())
        self.assertEqual(result, ([rfile], [], []))
        rfile.close()
        wfile.close()

    def test_default_selector_write_before(self) -> None:
        rfile, wfile = util.selectable_pipe()
        wfile.write(b"\0")
        selector = selectors.DefaultSelector()
        selector.register(rfile, selectors.EVENT_READ)
        events = selector.select()
        self.assertEqual(len(events), 1)
        key, _ = events[0]
        self.assertEqual(key.fileobj, rfile)
        rfile.close()
        wfile.close()

    def test_default_selector_write_from_thread(self) -> None:
        rfile, wfile = util.selectable_pipe()

        def write_from_thread() -> None:
            # Is there a way to synchronize this?
            time.sleep(0.1)
            wfile.write(b"\0")

        selector = selectors.DefaultSelector()
        selector.register(rfile, selectors.EVENT_READ)
        threading.Thread(target=write_from_thread).start()
        events = selector.select()
        self.assertEqual(len(events), 1)
        key, _ = events[0]
        self.assertEqual(key.fileobj, rfile)
        rfile.close()
        wfile.close()
