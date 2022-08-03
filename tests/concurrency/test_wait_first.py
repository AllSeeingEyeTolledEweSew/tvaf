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

from tests import conftest
from tvaf import concurrency


class DummyException(Exception):
    pass


@conftest.timeout(5)
async def test_first_completed() -> None:
    async def noop() -> None:
        pass

    forever = asyncio.get_event_loop().create_future()
    await concurrency.wait_first((noop(), forever))
    assert forever.done()
    assert forever.cancelled()


@conftest.timeout(5)
async def test_exception() -> None:
    async def raise_dummy() -> None:
        raise DummyException()

    forever = asyncio.get_event_loop().create_future()
    with pytest.raises(DummyException):
        await concurrency.wait_first((raise_dummy(), forever))
    assert forever.done()
    assert forever.cancelled()


async def test_cancel() -> None:
    # Cancel the *outer* task, only once the inner task is really running
    forever = asyncio.get_event_loop().create_future()

    async def cancel_task(task: asyncio.Future) -> None:
        task.cancel()
        await forever

    current_task = asyncio.current_task()
    assert current_task is not None
    with pytest.raises(asyncio.CancelledError):
        await concurrency.wait_first((forever, cancel_task(current_task)))
    assert forever.done()
    assert forever.cancelled()
