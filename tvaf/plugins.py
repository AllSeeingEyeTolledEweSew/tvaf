# Copyright (c) 2021 AllSeeingEyeTolledEweSew
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


import sys
from typing import Any
from typing import Callable
from typing import cast
from typing import Dict
from typing import Generic
from typing import Iterable
from typing import Mapping
from typing import Tuple
from typing import TypeVar
import warnings

from . import lifecycle

if sys.version_info >= (3, 8):
    import importlib.metadata as importlib_metadata
else:
    import importlib_metadata


def _entry_point_key(entry: importlib_metadata.EntryPoint) -> Tuple:
    return (entry.name, entry.value)


def _select_eps_group(
    group_name: str,
) -> Iterable[importlib_metadata.EntryPoint]:
    eps = importlib_metadata.entry_points()
    # The importlib_metadata backport has diverged from the stdlib version, and
    # emits DeprecationWarning if we use the dict interface
    if sys.version_info >= (3, 8):
        return eps.get(group_name, ())
    else:
        return cast(Tuple[importlib_metadata.EntryPoint], eps.select(group=group_name))


@lifecycle.lru_cache(maxsize=256)
def get(group_name: str) -> Mapping[str, Any]:
    name_to_entry_point: Dict[str, importlib_metadata.EntryPoint] = {}
    for entry_point in _select_eps_group(group_name):
        name = entry_point.name
        existing = name_to_entry_point.get(name, entry_point)
        if existing.value != entry_point.value:
            warnings.warn(
                "conflicting values for entry point "
                f"[{group_name} {name}]: "
                f"{entry_point.value} != {existing.value}"
            )
        name_to_entry_point[name] = entry_point
    return {name: ep.load() for name, ep in name_to_entry_point.items()}


_T = TypeVar("_T")


class Group(Generic[_T]):
    def __init__(self, group_name: str) -> None:
        self.group_name = group_name

    def get(self) -> Mapping[str, _T]:
        return get(self.group_name)


_C = TypeVar("_C", bound=Callable)


class Funcs(Group[_C]):
    def decorator(self, name: str) -> Callable[[_C], _C]:
        def wrap(func: _C) -> _C:
            value = f"{func.__module__}:{func.__qualname__}"
            for entry_point in _select_eps_group(self.group_name):
                if entry_point.name == name:
                    assert entry_point.value == value
                    break
            else:
                raise AssertionError(f"[{self.group_name} - {name}] not found")
            return func

        return wrap
