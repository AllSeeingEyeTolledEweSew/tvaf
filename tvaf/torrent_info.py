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

from typing import Any
from typing import cast
from typing import Dict
from typing import List
from typing import Tuple
from typing import Union

import libtorrent as lt
import multihash

from tvaf import lifecycle
from tvaf import ltpy
from tvaf import plugins
from tvaf import services
from tvaf.types import ConfigureATP

# design thoughts:

# class-based collection of functions:
#  - within each function, self.other_function refers only to the current
#    collection, instead of dispatching to all possible functions through
#    the normal method
# standalone functions using fastapi's DI:
#  - plugin architecture is mostly straightforward
#  - have to invent a way to inject a dynamic set of dependencies, to capture
#    plugins loaded at runtime
#  - can't be reused outside of request, unless we invent our own resolver
#  - DI is cached per request, can't be pre-cached unless we invent our own
#    resolver
# using global functions *without* fastapi's DI:
#  - test isolation is more error-prone than class-based dependencies
#  - (maybe equivalently so to any DI)


@lifecycle.lru_cache()
@plugins.dispatch()
def get_num_files(btmh: multihash.Multihash) -> int:
    ...


@lifecycle.lru_cache()
@plugins.dispatch()
def check_file_index(btmh: multihash.Multihash, file_index: int) -> None:
    ...


@lifecycle.lru_cache()
@plugins.dispatch()
def get_file_bounds(
    btmh: multihash.Multihash, file_index: int
) -> Tuple[int, int]:
    ...


@lifecycle.lru_cache()
@plugins.dispatch()
def get_file_path(
    btmh: multihash.Multihash, file_index: int
) -> List[Union[str, bytes]]:
    ...


@lifecycle.lru_cache()
@plugins.dispatch()
def get_file_name(
    btmh: multihash.Multihash, file_index: int
) -> Union[str, bytes]:
    ...


@lifecycle.lru_cache()
@plugins.dispatch()
def get_bencoded_info(btmh: multihash.Multihash) -> bytes:
    ...


@lifecycle.lru_cache()
@plugins.dispatch()
def get_parsed_info(btmh: multihash.Multihash) -> Dict[bytes, Any]:
    ...


@plugins.dispatch()
def get_configure_atp(btmh: multihash.Multihash) -> ConfigureATP:
    ...


def check_file_index_default(
    btmh: multihash.Multihash, file_index: int
) -> None:
    if file_index < 0 or file_index >= get_num_files(btmh):
        raise IndexError(file_index)


def get_file_name_default(
    btmh: multihash.Multihash, file_index: int
) -> Union[str, bytes]:
    path = get_file_path(btmh, file_index)
    if not path:
        raise plugins.Pass()
    return path[-1]


def get_parsed_info_default(btmh: multihash.Multihash) -> Dict[bytes, Any]:
    info = cast(Dict[bytes, Any], lt.bdecode(get_bencoded_info(btmh)))
    info.pop(b"pieces", None)
    return info


@lifecycle.lru_cache()
def _get_ti(btmh: multihash.Multihash) -> lt.torrent_info:
    handle = services.get_session().find_torrent(btmh)
    if not handle.is_valid():
        raise plugins.Pass()
    try:
        with ltpy.translate_exceptions():
            return handle.torrent_file()
    except ltpy.InvalidTorrentHandleError:
        raise plugins.Pass()


@lifecycle.lru_cache()
def _get_fs(btmh: multihash.Multihash) -> lt.file_storage:
    return _get_ti(btmh).orig_files()


def get_bencoded_info_from_session(btmh: multihash.Multihash) -> bytes:
    return _get_ti(btmh).metadata()


def get_file_path_from_parsed_info(
    btmh: multihash.Multihash, file_index: int
) -> List[Union[str, bytes]]:
    info = get_parsed_info(btmh)
    check_file_index(btmh, file_index)
    path: List[Union[str, bytes]] = []
    if b"name.utf-8" in info:
        name = cast(bytes, info[b"name.utf-8"])
        path.append(name.decode("utf-8"))
    else:
        name = cast(bytes, info[b"name"])
        path.append(name)
    if b"files" in info:
        file_info = info[b"files"][file_index]
        if b"path.utf-8" in file_info:
            file_path = cast(List[bytes], file_info[b"path.utf-8"])
            path.extend(part.decode("utf-8") for part in file_path)
        else:
            file_path = cast(List[bytes], file_info[b"path"])
            path.extend(file_path)
    return path


def get_num_files_from_session(btmh: multihash.Multihash) -> int:
    return _get_fs(btmh).num_files()


def get_file_bounds_from_session(
    btmh: multihash.Multihash, file_index: int
) -> Tuple[int, int]:
    fs = _get_fs(btmh)
    # Necessary, or fs will crash the process
    check_file_index(btmh, file_index)
    offset = fs.file_offset(file_index)
    return (offset, offset + fs.file_size(file_index))
