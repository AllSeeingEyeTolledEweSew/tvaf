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

from typing import Awaitable
from typing import Callable
from typing import Iterable
from typing import Tuple
from typing import TypeVar

import libtorrent as lt

from . import concurrency
from . import lifecycle
from . import plugins

_T = TypeVar("_T")


async def _first_from_plugins(aws: Iterable[Awaitable[_T]]) -> _T:
    # TODO: should we report unexpected exceptions from runners-up?
    with concurrency.as_completed_ctx(aws) as iterator:
        for future in iterator:
            try:
                return await future
            except KeyError:
                pass
    raise KeyError()


GetFileBoundsFromCache = Callable[[lt.info_hash_t, int], Awaitable[Tuple[int, int]]]
_GET_FILE_BOUNDS_FROM_CACHE_FUNCS: plugins.Funcs[
    GetFileBoundsFromCache
] = plugins.Funcs("tvaf.torrent_info.get_file_bounds_from_cache")
get_file_bounds_from_cache_plugin = _GET_FILE_BOUNDS_FROM_CACHE_FUNCS.decorator


@lifecycle.alru_cache(maxsize=256)
async def get_file_bounds_from_cache(
    info_hashes: lt.info_hash_t, file_index: int
) -> Tuple[int, int]:
    funcs = _GET_FILE_BOUNDS_FROM_CACHE_FUNCS.get().values()
    return await _first_from_plugins([func(info_hashes, file_index) for func in funcs])


IsPrivate = Callable[[lt.info_hash_t], Awaitable[bool]]
_IS_PRIVATE_FUNCS: plugins.Funcs[IsPrivate] = plugins.Funcs(
    "tvaf.torrent_info.is_private"
)
is_private_plugin = _IS_PRIVATE_FUNCS.decorator


@lifecycle.alru_cache(maxsize=256)
async def is_private(info_hashes: lt.info_hash_t) -> bool:
    funcs = _IS_PRIVATE_FUNCS.get().values()
    return await _first_from_plugins([func(info_hashes) for func in funcs])
