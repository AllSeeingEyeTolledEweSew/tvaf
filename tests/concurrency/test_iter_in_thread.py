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
import threading

import pytest

from tvaf import concurrency


class DummyException(Exception):
    pass


async def test_return_value() -> None:
    def iterator() -> Iterator[int]:
        yield 1
        yield 2
        yield 3

    aiterator = concurrency.iter_in_thread(iterator())
    values = [value async for value in aiterator]
    assert values == [1, 2, 3]


async def test_exception() -> None:
    def iterator() -> Iterator[int]:
        yield 1
        raise DummyException()

    aiterator = concurrency.iter_in_thread(iterator())
    with pytest.raises(DummyException):
        async for value in aiterator:
            pass


async def test_really_in_thread() -> None:
    def iterator() -> Iterator[int]:
        yield threading.get_ident()

    outside_ids = [threading.get_ident()]
    aiterator = concurrency.iter_in_thread(iterator())
    inside_ids = [value async for value in aiterator]
    assert outside_ids != inside_ids


async def test_small_batch_size() -> None:
    def iterator() -> Iterator[int]:
        yield from range(100)

    aiterator = concurrency.iter_in_thread(iterator(), batch_size=1)
    values = [value async for value in aiterator]
    assert values == list(range(100))


async def test_large_batch_size() -> None:
    def iterator() -> Iterator[int]:
        yield 1

    aiterator = concurrency.iter_in_thread(iterator(), batch_size=1000000)
    values = [value async for value in aiterator]
    assert values == [1]
