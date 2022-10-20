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
from __future__ import annotations

from collections.abc import Awaitable
import functools
from typing import Any
from typing import Callable
from typing import cast
from typing import Generic
from typing import TypeVar

import asyncstdlib

_C = TypeVar("_C", bound=Callable[..., Any])
_CA = TypeVar("_CA", bound=Callable[..., Awaitable])

_callbacks: list[Callable[[], Any]] = []


class _LRUCacheWrapper(Generic[_C]):
    __call__: _C

    def cache_clear(self) -> None:
        ...


def lru_cache(*, maxsize: int) -> Callable[[_C], _LRUCacheWrapper[_C]]:
    def wrapper(func: _C) -> _LRUCacheWrapper[_C]:
        wrapped = cast(_LRUCacheWrapper[_C], functools.lru_cache(maxsize=maxsize)(func))
        add_clear_callback(wrapped.cache_clear)
        return wrapped

    return wrapper


def singleton() -> Callable[[_C], _LRUCacheWrapper[_C]]:
    return lru_cache(maxsize=1)


def alru_cache(*, maxsize: int) -> Callable[[_CA], _LRUCacheWrapper[_CA]]:
    def wrapper(func: _CA) -> _LRUCacheWrapper[_CA]:
        wrapped = cast(
            _LRUCacheWrapper[_CA], asyncstdlib.lru_cache(maxsize=maxsize)(func)
        )
        add_clear_callback(wrapped.cache_clear)
        return wrapped

    return wrapper


def asingleton() -> Callable[[_CA], _LRUCacheWrapper[_CA]]:
    return alru_cache(maxsize=1)


def add_clear_callback(callback: Callable[[], Any]) -> None:
    _callbacks.append(callback)


def clear_all() -> None:
    for callback in _callbacks:
        callback()
