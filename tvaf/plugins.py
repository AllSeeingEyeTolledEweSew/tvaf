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


import collections
import sys
from typing import Any
from typing import cast
from typing import Iterable
from typing import List
from typing import Tuple

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
        return cast(
            Tuple[importlib_metadata.EntryPoint], eps.select(group=group_name)
        )


def get_entry_points(group_name: str) -> Iterable[Any]:
    name_to_entry_points = collections.defaultdict(list)
    for entry_point in _select_eps_group(group_name):
        name_to_entry_points[entry_point.name].append(entry_point)
    entry_points: List[importlib_metadata.EntryPoint] = []
    for _, values in sorted(name_to_entry_points.items()):
        entry_points.extend(values)
    return entry_points


@lifecycle.lru_cache(maxsize=256)
def load_entry_points(group_name: str) -> Iterable[Any]:
    return [entry.load() for entry in get_entry_points(group_name)]
