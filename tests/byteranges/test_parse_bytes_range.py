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

from tvaf import byteranges


def test_empty() -> None:
    with pytest.raises(ValueError):
        byteranges.parse_bytes_range("")


def test_not_bytes() -> None:
    with pytest.raises(ValueError):
        byteranges.parse_bytes_range("timestamps=")


def test_no_ranges() -> None:
    with pytest.raises(ValueError):
        byteranges.parse_bytes_range("bytes=")


def test_basic() -> None:
    slices = byteranges.parse_bytes_range("bytes=1-2")
    assert slices == [slice(1, 3)]


def test_tail() -> None:
    slices = byteranges.parse_bytes_range("bytes=1-")
    assert slices == [slice(1, None)]


def test_suffix() -> None:
    slices = byteranges.parse_bytes_range("bytes=-5")
    assert slices == [slice(-5)]


def test_dash() -> None:
    with pytest.raises(ValueError):
        byteranges.parse_bytes_range("bytes=-")


def test_multi() -> None:
    slices = byteranges.parse_bytes_range("bytes=1-2, 3-4")
    assert slices == [slice(1, 3), slice(3, 5)]
    slices = byteranges.parse_bytes_range("bytes=1-2, 1-")
    assert slices == [slice(1, 3), slice(1, None)]
    slices = byteranges.parse_bytes_range("bytes=1-2, -5")
    assert slices == [slice(1, 3), slice(-5)]


def test_whitespace() -> None:
    slices = byteranges.parse_bytes_range("bytes=1-2, 3-4")
    assert slices == [slice(1, 3), slice(3, 5)]
    slices = byteranges.parse_bytes_range("bytes=  1-2,  3-4  ")
    assert slices == [slice(1, 3), slice(3, 5)]
    slices = byteranges.parse_bytes_range("bytes=1-2,3-4")
    assert slices == [slice(1, 3), slice(3, 5)]
