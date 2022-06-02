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
import contextlib
import contextvars
import functools
import inspect
import itertools
from typing import Any
from typing import AsyncIterator
from typing import Awaitable
from typing import Callable
from typing import cast
from typing import Generic
from typing import Iterable
from typing import Iterator
from typing import MutableMapping
from typing import Optional
from typing import overload
from typing import TypeVar

import cachetools.keys

_T = TypeVar("_T")


async def to_thread(func: Callable[..., _T], *args: Any, **kwargs: Any) -> _T:
    """Runs a synchronous function in a thread.

    This is just a syntactic shortcut for
    asyncio.get_event_loop().run_in_executor().

    contextvars will be preserved when the function is run in the thread.

    Args:
        func: A synchronous function to be called in a thread.
        args: Arguments to the function.
        kwargs: Keyword arguments to the function.

    Returns:
        The function's return value.
    """
    loop = asyncio.get_event_loop()
    context = contextvars.copy_context()
    # Not sure why this cast is required
    bound = cast(
        Callable[..., _T],
        functools.partial(context.run, func, *args, **kwargs),
    )
    return await loop.run_in_executor(None, bound)


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
        batch = await to_thread(iter_batch)
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


_CA = TypeVar("_CA", bound=Callable[..., Awaitable])


def acached(cache: MutableMapping) -> Callable[[_CA], _CA]:
    """Decorates an asynchronous function with a cache.

    This is analogous to cachetools.cached(), for asynchronous functions.

    Args:
        cache: A mapping to use as a cache. A common choice is
            cachetools.LRUCache.

    Returns:
        A decorator function which takes an asynchronous function as input,
        and returns an asynchronous function which caches its results.
    """

    def wrapper(func: _CA) -> _CA:
        @functools.wraps(func)
        async def wrapped(*args: Any, **kwargs: Any) -> Any:
            key = cachetools.keys.hashkey(*args, **kwargs)
            try:
                return cache[key]
            except KeyError:
                pass
            value = await func(*args, **kwargs)
            cache[key] = value
            return value

        return cast(_CA, wrapped)

    return wrapper


class _AcachedProperty(Generic[_T]):
    def __init__(self, func: Callable[[Any], Awaitable[_T]]) -> None:
        self._func = func
        self._name: Optional[str] = None
        self.__doc__ = func.__doc__

    def __set_name__(self, owner: Any, name: str) -> None:
        self._name = name

    @overload
    def __get__(self, instance: None, owner: type = None) -> _AcachedProperty[_T]:
        ...

    @overload
    def __get__(self, instance: object, owner: type = None) -> Awaitable[_T]:
        ...

    def __get__(self, instance: Any, owner: Any = None) -> Any:
        if instance is None:
            return self
        attrs = instance.__dict__
        if self._name not in attrs:
            attrs[self._name] = ensure_future(self._func(instance))
        return attrs[self._name]


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


# This could be 'class acached_property', but this setup helps linters
def acached_property(func: Callable[[Any], Awaitable[_T]]) -> _AcachedProperty[_T]:
    """Turns an asynchronous method into an awaitable property.

    This is analogous to @functools.cached_property, for asynchronous
    functions.

    When the property is first accessed, its accessor function will be
    scheduled with asyncio.create_task(). That Task will be returned on
    subsequent access, so it can be awaited multiple times.

    Args:
        func: A property accessor function.

    Returns:
        An awaitable property.
    """
    return _AcachedProperty(func)


async def alist(it: AsyncIterator[_T]) -> list[_T]:
    """Returns an AsyncIterator as a list."""
    return [item async for item in it]


async def as_completed(
    aws: Iterable[Awaitable[_T]],
) -> AsyncIterator[asyncio.Future[_T]]:
    """Yields coroutines in the order they complete.

    This is like asyncio.as_completed(), but the tasks will be cancelled when
    the generator is cleaned up. This makes it simple for a caller to spawn
    several coroutines, find the first result matching a condition, and cancel
    the rest.

    As with asyncio.as_completed(), the awaitables will be scheduled as tasks.

    Args:
        aws: Awaitables to iterate over.

    Returns:
        An iterator of futures, in completion order.
    """
    tasks = {ensure_future(aw) for aw in aws}
    try:
        for future in asyncio.as_completed(tasks):
            yield future
    finally:
        for task in tasks:
            task.cancel()


@contextlib.contextmanager
def as_completed_ctx(
    aws: Iterable[Awaitable[_T]],
) -> Iterator[Iterator[asyncio.Future[_T]]]:
    """Yields coroutines in the order they complete.

    This is the same as as_completed(), except that tasks will be immediately
    cancelled when the context manager exits. This makes cancellation more
    timely.

    Args:
        aws: Awaitables to iterate over.

    Returns:
        A context manager whose value is an iterator of futures. The futures
        will represent the results of the input awaitables, in completion
        order.
    """
    tasks = {ensure_future(aw) for aw in aws}
    try:
        yield asyncio.as_completed(tasks)
    finally:
        for task in tasks:
            task.cancel()


class _MissingType:
    pass


_MISSING = _MissingType()


def create_future(result: Any = _MISSING) -> asyncio.Future:
    """Returns an asyncio.Future with optional pre-set result."""
    future = asyncio.get_event_loop().create_future()
    if result is not _MISSING:
        future.set_result(result)
    return future
