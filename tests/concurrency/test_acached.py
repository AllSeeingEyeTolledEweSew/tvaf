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

from typing import Any

from tvaf import concurrency


async def test_cache() -> None:
    cache: dict = {}
    call_count = 0

    @concurrency.acached(cache)
    async def func(*args: Any, **kwargs: Any) -> None:
        nonlocal call_count
        call_count += 1

    # Initial calls
    await func(1, a=2)
    await func(3, a=4)
    assert call_count == 2

    # Subsequent calls should be cached
    call_count = 0
    await func(1, a=2)
    await func(3, a=4)
    assert call_count == 0

    # We should be able to clear the cache
    cache.clear()
    await func(1, a=2)
    await func(3, a=4)
    assert call_count == 2
