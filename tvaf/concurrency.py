# Copyright (c) 2020 AllSeeingEyeTolledEweSew
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
from __future__ import annotations

import asyncio
import contextvars
import functools
import itertools
from typing import Any
from typing import AsyncIterator
from typing import Awaitable
from typing import Callable
from typing import cast
from typing import Generator
from typing import Generic
from typing import Iterable
from typing import Iterator
from typing import List
from typing import MutableMapping
from typing import Optional
from typing import overload
from typing import Type
from typing import TypeVar
from typing import Union

import cachetools.keys

_T = TypeVar("_T")
_FutureT = Union["asyncio.Future[_T]", Generator[Any, None, _T], Awaitable[_T]]


async def to_thread(func: Callable[..., _T], *args: Any, **kwargs: Any) -> _T:
    loop = asyncio.get_event_loop()
    context = contextvars.copy_context()
    # Not sure why this cast is required
    bound = cast(
        Callable[..., _T],
        functools.partial(context.run, func, *args, **kwargs),
    )
    return await loop.run_in_executor(None, bound)


async def iter_in_thread(
    iterator: Iterator[_T], batch_size=100
) -> AsyncIterator[_T]:
    def iter_batch() -> List[_T]:
        return list(itertools.islice(iterator, batch_size))

    while True:
        batch = await to_thread(iter_batch)
        if not batch:
            break
        for obj in batch:
            yield obj


async def wait_error(job: "asyncio.Future[_T]", error: asyncio.Future) -> _T:
    await asyncio.wait((job, error), return_when=asyncio.FIRST_COMPLETED)
    if error.done():
        error.result()  # should raise
    assert job.done()
    return job.result()


async def wait_first(aws: Iterable[_FutureT]) -> None:
    tasks = [asyncio.create_task(aw) for aw in aws]
    (done, pending) = await asyncio.wait(
        tasks, return_when=asyncio.FIRST_COMPLETED
    )
    for task in pending:
        task.cancel()
    for task in done:
        task.result()


class RefCount:
    def __init__(self) -> None:
        self._count = 0
        self._is_zero = asyncio.Event()
        self._is_zero.set()

    def acquire(self) -> None:
        self._count += 1
        self._is_zero.clear()

    def release(self) -> None:
        if self._count <= 0:
            raise ValueError()
        self._count -= 1
        if self._count == 0:
            self._is_zero.set()

    def count(self) -> int:
        return self._count

    async def wait_zero(self) -> None:
        while self._count != 0:
            await self._is_zero.wait()


_CA = TypeVar("_CA", bound=Callable[..., Awaitable])


def acached(cache: MutableMapping) -> Callable[[_CA], _CA]:
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


class acached_property(Generic[_T]):  # noqa: N801
    def __init__(self, func: Callable[[Any], Awaitable[_T]]) -> None:
        self._func = func
        self._name: Optional[str] = None
        self.__doc__ = func.__doc__

    def __set_name__(self, owner: Any, name: str) -> None:
        self._name = name

    @overload
    def __get__(
        self, instance: None, owner: Type = None
    ) -> acached_property[_T]:
        ...

    @overload
    def __get__(self, instance: object, owner: Type = None) -> Awaitable[_T]:
        ...

    def __get__(self, instance: Any, owner: Any = None) -> Any:
        if instance is None:
            return self
        attrs = instance.__dict__
        if self._name not in attrs:
            attrs[self._name] = asyncio.create_task(self._func(instance))
        return attrs[self._name]


async def alist(it: AsyncIterator[_T]) -> List[_T]:
    return [item async for item in it]
