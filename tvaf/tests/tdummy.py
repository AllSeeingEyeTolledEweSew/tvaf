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

import hashlib
import random
from typing import Any
from typing import Callable
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple
from typing import Type
from typing import TypeVar
from typing import Union

import libtorrent as lt
from typing_extensions import TypedDict

from tvaf import multihash

from . import lib

PIECE_LENGTH = 16384
NAME = b"test.txt"
LEN = PIECE_LENGTH * 9 + 1000
DATA = bytes(random.getrandbits(7) for _ in range(LEN))
PIECES = [DATA[i : i + PIECE_LENGTH] for i in range(0, LEN, PIECE_LENGTH)]

INFO_DICT = {
    b"name": NAME,
    b"piece length": PIECE_LENGTH,
    b"length": len(DATA),
    b"pieces": b"".join(hashlib.sha1(p).digest() for p in PIECES),
}

DICT = {
    b"info": INFO_DICT,
}

INFOHASH_BYTES = hashlib.sha1(lt.bencode(INFO_DICT)).digest()
INFOHASH = INFOHASH_BYTES.hex()
SHA1_HASH = lt.sha1_hash(INFOHASH_BYTES)


class _FParams(TypedDict, total=False):
    length: int
    data: Optional[bytes]
    path: Optional[bytes]
    path_split: Optional[List[bytes]]
    attr: Optional[bytes]


class File:
    def __init__(
        self,
        *,
        length: int,
        start: int,
        stop: int,
        data: bytes = None,
        path: bytes = None,
        path_split: List[bytes] = None,
        attr: bytes = None
    ):
        assert stop - start == length, (start, stop, length)
        if data is not None:
            assert len(data) == length

        if path is None:
            assert path_split is not None
            path = b"/".join(path_split)
        if path_split is None:
            assert path is not None
            path_split = path.split(b"/")

        self._data = data
        self.path = path
        self.path_split = path_split
        self.length = length
        self.attr = attr or b""
        self.start = start
        self.stop = stop

    @property
    def data(self) -> bytes:
        if b"p" in self.attr:
            return b"\x00" * self.length
        if self._data is None:
            # 7-bit data to make it easy to work around libtorrent bug #4612
            self._data = bytes(
                random.getrandbits(7) for _ in range(self.length)
            )
        return self._data


_T = TypeVar("_T", bound="Torrent")


class Torrent:
    @classmethod
    def single_file(
        cls: Type[_T],
        *,
        length: int,
        piece_length: int = 16384,
        name: bytes = None,
        attr: bytes = None,
        data: bytes = None
    ) -> _T:
        return cls(
            piece_length=piece_length,
            files=[
                _FParams(length=length, path=name, attr=attr, data=data),
            ],
        )

    def __init__(self, *, files: List[_FParams], piece_length: int = 16384):
        assert piece_length is not None

        self.piece_length = piece_length
        self.files: List[File] = []

        offset = 0
        for file_ in files:
            start = offset
            stop = offset + file_["length"]
            offset = stop
            self.files.append(File(start=start, stop=stop, **file_))
        self.length = sum(f.length for f in self.files)

        self._data: Optional[bytes] = None
        self._pieces: Optional[List[bytes]] = None
        self._info: Optional[Dict[bytes, Any]] = None
        self._dict: Optional[Dict[bytes, Any]] = None
        self._info_hash_bytes: Optional[bytes] = None
        self._eps: Optional[lib.EntryPointFaker] = None

    @property
    def data(self) -> bytes:
        if self._data is None:
            self._data = b"".join(f.data for f in self.files)
        return self._data

    @property
    def pieces(self) -> List[bytes]:
        if self._pieces is None:
            self._pieces = [
                self.data[i : i + self.piece_length]
                for i in range(0, self.length, self.piece_length)
            ]
        return self._pieces

    @property
    def info(self) -> Dict[bytes, Any]:
        if self._info is None:
            self._info = {
                b"piece length": self.piece_length,
                b"length": self.length,
                b"pieces": b"".join(
                    hashlib.sha1(p).digest() for p in self.pieces
                ),
            }

            if len(self.files) == 1:
                self._info[b"name"] = self.files[0].path
            else:
                assert len({f.path_split[0] for f in self.files}) == 1
                assert all(len(f.path_split) > 1 for f in self.files)
                self._info[b"name"] = self.files[0].path_split[0]
                self._info[b"files"] = []
                for file_ in self.files:
                    fdict = {
                        b"length": file_.length,
                        b"path": file_.path_split[1:],
                    }
                    if file_.attr:
                        fdict[b"attr"] = file_.attr
                    self._info[b"files"].append(fdict)
        return self._info

    @property
    def dict(self) -> Dict[bytes, Any]:
        if self._dict is None:
            self._dict = {
                b"info": self.info,
            }
        return self._dict

    @property
    def info_hash_bytes(self) -> bytes:
        if self._info_hash_bytes is None:
            self._info_hash_bytes = hashlib.sha1(
                lt.bencode(self.info)
            ).digest()
        return self._info_hash_bytes

    @property
    def sha1_hash(self) -> lt.sha1_hash:
        return lt.sha1_hash(self.info_hash_bytes)

    @property
    def btmh(self) -> multihash.Multihash:
        return multihash.Multihash(multihash.Func.sha1, self.info_hash_bytes)

    def torrent_info(self) -> lt.torrent_info:
        return lt.torrent_info(self.dict)

    def atp(self) -> lt.add_torrent_params:
        atp = lt.add_torrent_params()
        self.configure_atp(atp)
        return atp

    @property
    def entry_point_faker(self) -> lib.EntryPointFaker:
        if self._eps is None:
            self._eps = lib.EntryPointFaker()
            self._eps.add(
                "_tdummy",
                self.get_configure_atp,
                "tvaf.torrent_info.get_configure_atp",
            )
            self._eps.add(
                "_tdummy",
                self.get_file_bounds_from_cache,
                "tvaf.torrent_info.get_file_bounds_from_cache",
            )
        return self._eps

    def configure_atp(self, atp: lt.add_torrent_params) -> None:
        # this is necessary so that
        # atp == read_resume_data(write_resume_data(atp))
        atp.info_hash = self.sha1_hash
        atp.ti = self.torrent_info()

    def _check_btmh(self, btmh: multihash.Multihash) -> None:
        if btmh != self.btmh:
            raise KeyError()

    async def get_configure_atp(
        self, btmh: multihash.Multihash
    ) -> Callable[[lt.add_torrent_params], Any]:
        self._check_btmh(btmh)

        async def configure_atp(atp: lt.add_torrent_params) -> None:
            self.configure_atp(atp)

        return configure_atp

    async def get_file_bounds_from_cache(
        self, btmh: multihash.Multihash, file_index: int
    ) -> Tuple[int, int]:
        self._check_btmh(btmh)
        file_info = self.files[file_index]
        return (file_info.start, file_info.stop)

    async def get_file_name(
        self, btmh: multihash.Multihash, file_index: int
    ) -> Union[str, bytes]:
        self._check_btmh(btmh)
        return self.files[file_index].path_split[-1]


DEFAULT = Torrent.single_file(
    piece_length=16384, name=b"test.txt", length=16384 * 9 + 1000
)
DEFAULT_STABLE = Torrent.single_file(
    piece_length=16384,
    name=b"test.txt",
    length=16384 * 9 + 1000,
    data=b"\0" * (16384 * 9 + 1000),
)
