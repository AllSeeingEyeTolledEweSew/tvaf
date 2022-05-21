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


def test_full_range() -> None:
    it = util.iter_bitmap(b"\x00\x08", 0, 16)
    assert next(it) is False
    assert next(it) is False
    assert next(it) is False
    assert next(it) is False
    assert next(it) is False
    assert next(it) is False
    assert next(it) is False
    assert next(it) is False
    assert next(it) is False
    assert next(it) is False
    assert next(it) is False
    assert next(it) is False
    assert next(it) is True
    assert next(it) is False
    assert next(it) is False
    assert next(it) is False
    with pytest.raises(StopIteration):
        next(it)


def test_sub_range() -> None:
    it = util.iter_bitmap(b"\x00\x08", 12, 16)
    assert next(it) is True
    assert next(it) is False
    assert next(it) is False
    assert next(it) is False
    with pytest.raises(StopIteration):
        next(it)
