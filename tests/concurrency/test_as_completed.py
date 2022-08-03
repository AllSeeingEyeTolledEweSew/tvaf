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

from tests import conftest
from tvaf import concurrency


@conftest.timeout(5)
async def test_cleanup() -> None:
    async def returner_func() -> int:
        return 0

    returner = returner_func()
    forever = asyncio.get_event_loop().create_future()

    async for future in concurrency.as_completed([forever, returner]):
        assert (await future) == 0
        break

    # Test that the forever-waiting future is eventually cancelled

    # NB: for the async generator to be cleaned up, it must be marked
    # for cleanup by garbage collection, then __aexit__ is invoked by
    # the event loop
    while not forever.done():
        await asyncio.sleep(0)
