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

import pytest

from tvaf import util


def test_empty() -> None:
    it = util.enum_piece_is_set(b"\x80", 1024, 1000, 1000)
    with pytest.raises(StopIteration):
        next(it)


def test_non_edge_cases() -> None:
    it = util.enum_piece_is_set(b"\x80", 1024, 1000, 2000)
    assert next(it) == (0, True)
    assert next(it) == (1, False)
    with pytest.raises(StopIteration):
        next(it)


def test_edge_cases() -> None:
    it = util.enum_piece_is_set(b"\x80", 1024, 0, 2048)
    assert next(it) == (0, True)
    assert next(it) == (1, False)
    with pytest.raises(StopIteration):
        next(it)
