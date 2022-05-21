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

"""Utility functions for tvaf."""
from __future__ import annotations

import io
import os
import socket
import sys
from typing import Iterator


def bitmap_is_set(bitmap: bytes, i: int) -> bool:
    """Returns True if bitmap is set at the i'th bit."""
    assert (i >> 3) < len(bitmap), f"{i} out of range ({len(bitmap)})"
    return bool(bitmap[i >> 3] & (0x80 >> (i & 7)))


def iter_bitmap(bitmap: bytes, start: int, stop: int) -> Iterator[bool]:
    """Yields a boolean for the i'th bit in bitmap, for start <= i < stop."""
    for i in range(start, stop):
        yield bitmap_is_set(bitmap, i)


def range_to_pieces(piece_length: int, start: int, stop: int) -> tuple[int, int]:
    """Converts a range of bytes to a range of pieces.

    Pieces are assumed to be zero-aligned.

    Args:
        piece_length: The length of a piece.
        start: The first byte of the range.
        stop: The last byte of the range, plus one.

    Returns:
        A (start_piece, stop_piece) tuple, where start_piece is the first piece
            overlapping the input range, and stop_piece is the last piece
            overlapping the input range, plus one.
    """
    # Any cleaner way to do this?
    if stop <= start:
        return (start // piece_length, start // piece_length)
    return (start // piece_length, (stop - 1) // piece_length + 1)


def enum_piece_is_set(
    bitmap: bytes, piece_length: int, start: int, stop: int
) -> Iterator[tuple[int, bool]]:
    """Yields a (piece, is_set) tuple for each piece of a byte range.

    The given byte range (start, stop) is converted to a piece range. For every
    piece in that piece range, this function yields a (piece, is_set) tuple.

    Args:
        bitmap: A piece-indexed bitmap.
        piece_length: The length of a piece.
        start: The first byte of the range.
        stop: The last byte of the range, plus one.

    Yields:
        A (piece, is_set) tuple, for each piece overlapping the input range.
    """
    for piece in range(*range_to_pieces(piece_length, start, stop)):
        yield (piece, bitmap_is_set(bitmap, piece))


def iter_piece_is_set(
    bitmap: bytes, piece_length: int, start: int, stop: int
) -> Iterator[bool]:
    """Yields whether each piece overlapping a byte range is set.

    The given byte range (start, stop) is converted to a piece range. For every
    piece in that piece range, this function yields whether the corresponding
    bit in bitmap is set.

    Args:
        bitmap: A piece-indexed bitmap.
        piece_length: The length of a piece.
        start: The first byte of the range.
        stop: The last byte of the range, plus one.

    Yields:
        A boolean for each bit in bitmap, corresponding to pieces overlapping
            the given byte range.
    """
    for _, is_set in enum_piece_is_set(bitmap, piece_length, start, stop):
        yield is_set


def enum_piecewise_ranges(
    piece_length: int, start: int, stop: int
) -> Iterator[tuple[int, int, int]]:
    """Splits a byte range into smaller piece-aligned ranges.

    The given byte range (start, stop) is split into smaller sub-ranges, such
    that each sub-range overlaps exactly one piece of piece_length.

    Args:
        piece_length: The length of a piece.
        start: The first byte of the range.
        stop: The last byte of the range, plus one.

    Yields:
        Tuples of (piece, start, stop).
    """
    for piece in range(*range_to_pieces(piece_length, start, stop)):
        r_start = piece * piece_length
        r_stop = (piece + 1) * piece_length
        if r_start < start:
            r_start = start
        if r_stop > stop:
            r_stop = stop
        yield piece, r_start, r_stop


def selectable_pipe() -> tuple[io.RawIOBase, io.RawIOBase]:
    if sys.platform == "win32":
        rsock, wsock = socket.socketpair()
        rsock.setblocking(False)
        wsock.setblocking(False)
        # NB: buffering=None implies a *default buffer size*; buffering=0 is
        # required for an unbuffered object
        rfile = rsock.makefile(mode="rb", buffering=0)
        wfile = wsock.makefile(mode="wb", buffering=0)
        return rfile, wfile
    rfd, wfd = os.pipe()
    os.set_blocking(rfd, False)
    os.set_blocking(wfd, False)
    return io.FileIO(rfd, mode="rb"), io.FileIO(wfd, mode="wb")
