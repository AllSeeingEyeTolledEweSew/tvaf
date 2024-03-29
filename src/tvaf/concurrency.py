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
"""Asyncio utility functions for tvaf."""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from collections.abc import Awaitable
from collections.abc import Iterable
from collections.abc import Iterator
import inspect
import itertools
from typing import Any
from typing import TypeVar

_T = TypeVar("_T")


async def iter_in_thread(iterator: Iterator[_T], batch_size=100) -> AsyncIterator[_T]:
    """Runs a synchronous Iterator in a thread, in batches.

    This turns an Iterator into an AsyncIterator. To reduce context switching,
    we extract results from the iterator in batches.

    Choose batch_size with care. If reading large files, use a small
    batch_size. If extracting rows from sqlite, use a large batch_size.

    Batching means that the caller may be artifically delayed from seeing an
    object from the iterator. Don't use this if timely handling of each object
    is important.

    Args:
        iterator: A synchronous Iterator to run in a thread.
        batch_size: The maximum number of objects to retrieve from the iterator
            in the thread, before yielding them.

    Yields:
        Objects from the input iterator.
    """

    def iter_batch() -> list[_T]:
        return list(itertools.islice(iterator, batch_size))

    while True:
        batch = await asyncio.to_thread(iter_batch)
        if not batch:
            break
        for obj in batch:
            yield obj


async def wait_first(aws: Iterable[Awaitable]) -> None:
    """Wait for the first task to complete, and cancel the others.

    All awaitables will be done after wait_first finishes.

    Args:
        aws: Tasks to wait for.

    Raises:
        Any exceptions raised by the first completed task, including
        asyncio.CancelledError.
    """
    tasks = [ensure_future(aw) for aw in aws]
    try:
        (done, pending) = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    except asyncio.CancelledError:
        for task in tasks:
            task.cancel()
        raise
    for task in pending:
        task.cancel()
    for task in done:
        task.result()


class RefCount:
    """An asyncio reference counter.

    This is useful for the case where there may be several tasks which touch a
    resource, and some "master" task must wait for them all to complete.

    RefCount is complementary to a semaphore: instead of waiting for work
    capacity to become available before starting a task, it waits for many
    tasks to finish.

    RefCount has an internal counter, which is initially zero. You should
    increment the counter when a task starts, and decrement the counter when a
    task completes.

    RefCount is similar to asyncio.gather() but doesn't require each task to be
    represented by an awaitable.
    """

    def __init__(self) -> None:
        """Constructs a new RefCount whose internal counter is zero."""
        self._count = 0
        self._is_zero = asyncio.Event()
        self._is_zero.set()

    def acquire(self) -> None:
        """Increments the internal counter."""
        self._count += 1
        self._is_zero.clear()

    def release(self) -> None:
        """Decrements the internal counter."""
        if self._count <= 0:
            raise ValueError()
        self._count -= 1
        if self._count == 0:
            self._is_zero.set()

    def count(self) -> int:
        """Returns the internal counter."""
        return self._count

    async def wait_zero(self) -> None:
        """Waits until the internal counter is zero."""
        while self._count != 0:
            await self._is_zero.wait()


def ensure_future(aw: Awaitable[_T]) -> asyncio.Future[_T]:
    """Schedules any awaitable as a task.

    This utility function is modeled after the behavior of asyncio.ensure_future()
    (for versions >=3.5.1 and <3.10), which is being deprecated for some reason.

    If the input is a coroutine (tested with asyncio.iscoroutine()), the return value
    will be a task scheduled with asyncio.create_task().

    If the input is an asyncio.Future (tested with asyncio.isfuture()), it is returned
    directly.

    If the input is any awaitable (tested with inspect.isawaitable()), it is wrapped in
    a coroutine, scheduled as a task and returned.

    Any other value will raise TypeError.

    Args:
        aw: Any awaitable.

    Returns:
        A scheduled asyncio.Task.

    Raises:
        TypeError: If aw is not one of the supported types.
    """
    if asyncio.iscoroutine(aw):
        return asyncio.create_task(aw)
    if asyncio.isfuture(aw):
        return aw
    if inspect.isawaitable(aw):

        async def _wrapper() -> _T:
            return await aw

        return asyncio.create_task(_wrapper())
    raise TypeError("An asyncio.Future, a coroutine, or an awaitable is required")


class _MissingType:
    pass


_MISSING = _MissingType()


def create_future(result: Any = _MISSING) -> asyncio.Future:
    """Returns an asyncio.Future with optional pre-set result."""
    future = asyncio.get_event_loop().create_future()
    if result is not _MISSING:
        future.set_result(result)
    return future
