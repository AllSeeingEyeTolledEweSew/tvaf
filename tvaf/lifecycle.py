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

import functools
from typing import Any
from typing import Callable
from typing import cast
from typing import Generic
from typing import List
from typing import TypeVar

_C = TypeVar("_C", bound=Callable[..., Any])

_callbacks: List[Callable[[], Any]] = []


class _LRUCacheWrapper(Generic[_C]):
    __call__: _C

    def cache_clear(self) -> None:
        ...


def lru_cache() -> Callable[[_C], _LRUCacheWrapper[_C]]:
    def wrapper(func: _C) -> _LRUCacheWrapper[_C]:
        wrapped = cast(_LRUCacheWrapper[_C], functools.lru_cache()(func))
        _callbacks.append(wrapped.cache_clear)
        return wrapped

    return wrapper


singleton = lru_cache


def clear() -> None:
    for callback in _callbacks:
        callback()
