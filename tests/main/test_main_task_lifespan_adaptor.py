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
from collections.abc import AsyncIterator
from typing import NamedTuple
import unittest.mock

import pytest

from tests import conftest
from tvaf._internal import main


class Mocks(NamedTuple):
    mtla: main.MainTaskLifespanAdaptor
    do_startup: unittest.mock.AsyncMock
    do_shutdown: unittest.mock.AsyncMock


class FakeError(Exception):
    pass


async def raise_fake_error() -> None:
    raise FakeError()


@pytest.fixture
async def mock_startup() -> unittest.mock.AsyncMock:
    return unittest.mock.AsyncMock()


@pytest.fixture
async def mock_shutdown() -> unittest.mock.AsyncMock:
    return unittest.mock.AsyncMock()


@pytest.fixture
async def mock_mtla(
    mock_startup: unittest.mock.AsyncMock, mock_shutdown: unittest.mock.AsyncMock
) -> AsyncIterator[main.MainTaskLifespanAdaptor]:
    mtla = main.MainTaskLifespanAdaptor(mock_startup, mock_shutdown)
    try:
        yield mtla
    finally:
        mtla.cancel()


@pytest.fixture
def mocks(
    mock_mtla: main.MainTaskLifespanAdaptor,
    mock_startup: unittest.mock.AsyncMock,
    mock_shutdown: unittest.mock.AsyncMock,
) -> Mocks:
    return Mocks(mock_mtla, mock_startup, mock_shutdown)


@conftest.timeout(60)
async def test_normal(mocks: Mocks) -> None:
    await mocks.mtla.startup()
    mocks.do_startup.assert_awaited_once()
    await mocks.mtla.shutdown()
    mocks.do_shutdown.assert_awaited_once()


@conftest.timeout(60)
async def test_startup_error(mocks: Mocks) -> None:
    mocks.mtla.do_startup = raise_fake_error
    with pytest.raises(FakeError):
        await mocks.mtla.startup()


@conftest.timeout(60)
async def test_shutdown_error(mocks: Mocks) -> None:
    mocks.mtla.do_shutdown = raise_fake_error
    await mocks.mtla.startup()
    mocks.do_startup.assert_awaited_once()
    with pytest.raises(FakeError):
        await mocks.mtla.shutdown()


@conftest.timeout(60)
async def test_start_soon_in_startup(mocks: Mocks) -> None:
    task_future: asyncio.Future[asyncio.Task] = asyncio.get_event_loop().create_future()

    async def set_future() -> None:
        task = asyncio.current_task()
        assert task is not None
        task_future.set_result(task)

    async def startup_with_start_soon() -> None:
        mocks.mtla.start_soon(set_future)

    mocks.mtla.do_startup = startup_with_start_soon
    await mocks.mtla.startup()
    task = await task_future
    await task
    await mocks.mtla.shutdown()
    mocks.do_shutdown.assert_awaited_once()


@conftest.timeout(60)
async def test_start_soon_after_startup(mocks: Mocks) -> None:
    await mocks.mtla.startup()
    mocks.do_startup.assert_awaited_once()

    task_future: asyncio.Future[asyncio.Task] = asyncio.get_event_loop().create_future()

    async def set_future() -> None:
        task = asyncio.current_task()
        assert task is not None
        task_future.set_result(task)

    mocks.mtla.start_soon(set_future)
    task = await task_future
    await task

    await mocks.mtla.shutdown()
    mocks.do_shutdown.assert_awaited_once()


@conftest.timeout(60)
async def test_error_in_subtask_fails_shutdown(mocks: Mocks) -> None:
    await mocks.mtla.startup()
    mocks.do_startup.assert_awaited_once()

    mocks.mtla.start_soon(raise_fake_error)

    with pytest.raises(Exception):  # ExceptionGroup or the like
        await mocks.mtla.shutdown()
