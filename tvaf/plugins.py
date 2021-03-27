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


import collections
import functools
import sys
from typing import Any
from typing import Callable
from typing import cast
from typing import Iterable
from typing import List
from typing import Tuple
from typing import TypeVar

from tvaf import lifecycle

if sys.version_info >= (3, 8):
    import importlib.metadata as importlib_metadata
else:
    import importlib_metadata


def _entry_point_key(entry: importlib_metadata.EntryPoint) -> Tuple:
    return (entry.name, entry.value)


@lifecycle.lru_cache()
def get_entry_points(group_name: str) -> Iterable[Any]:
    name_to_entry_points = collections.defaultdict(list)
    for entry_point in importlib_metadata.entry_points().get(group_name, ()):
        name_to_entry_points[entry_point.name].append(entry_point)
    entry_points: List[importlib_metadata.EntryPoint] = []
    for _, values in sorted(name_to_entry_points.items()):
        values = sorted(values, key=_entry_point_key)
        entry_points.append(values[-1])
    return entry_points


@lifecycle.lru_cache()
def get_plugins(group_name: str) -> Iterable[Any]:
    return [entry.load() for entry in get_entry_points(group_name)]


_C = TypeVar("_C", bound=Callable[..., Any])


@lifecycle.lru_cache()
def get_plugins_for_func(func: _C) -> Iterable[_C]:
    group_name = f"{func.__module__}.{func.__qualname__}"
    return get_plugins(group_name)


class Pass(Exception):
    pass


def dispatch() -> Callable[[_C], _C]:
    def wrapper(func: _C) -> _C:
        @functools.wraps(func)
        def call_first(*args: Any, **kwargs: Any) -> Any:
            for plugin in get_plugins_for_func(func):
                try:
                    return plugin(*args, **kwargs)
                except Pass:
                    pass
            raise Pass()

        return cast(_C, call_first)

    return wrapper
