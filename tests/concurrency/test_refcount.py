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

import pytest

from tvaf import concurrency


async def test_count() -> None:
    refcount = concurrency.RefCount()
    assert refcount.count() == 0
    refcount.acquire()
    assert refcount.count() == 1
    refcount.release()
    assert refcount.count() == 0


async def test_release_below_zero() -> None:
    refcount = concurrency.RefCount()
    with pytest.raises(ValueError):
        refcount.release()


async def test_wait_zero() -> None:
    refcount = concurrency.RefCount()
    await refcount.wait_zero()
    refcount.acquire()

    async def do_release() -> None:
        refcount.release()

    task = asyncio.create_task(do_release())
    await refcount.wait_zero()
    await task
