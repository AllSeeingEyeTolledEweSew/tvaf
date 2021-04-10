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

import enum
import io
from typing import Any
from typing import Callable
from typing import Dict
from typing import Iterator
from typing import Tuple
from typing import Type
from typing import TypeVar

import pydantic.utils

# I think the official python multihash implementation has some issues, so I
# made my own.


class Func(enum.IntEnum):
    sha1 = 0x11
    sha2_256 = 0x12


def _read_varint(value: bytes, offset: int) -> Tuple[int, int]:
    result = 0
    shift = 0
    while True:
        if offset >= len(value):
            raise ValueError("invalid varint")
        byte = value[offset]
        offset += 1
        result |= (byte & 0x7F) << shift
        shift += 7
        if not (byte & 0x80):
            break
    return result, offset


def _write_varint(value: int, fp: io.BytesIO) -> None:
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            byte |= 0x80
        fp.write(bytes((byte,)))
        if not value:
            break


_M = TypeVar("_M", bound="Multihash")


# I modeled this like pydantic's NameEmail
class Multihash(pydantic.utils.Representation):
    __slots__ = ("func", "digest")

    def __init__(self, func: int, digest: bytes) -> None:
        self.func = func
        self.digest = digest

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, Multihash) and (self.func, self.digest) == (
            other.func,
            other.digest,
        )

    @classmethod
    def __modify_schema__(cls, field_schema: Dict[str, Any]) -> None:
        field_schema.update({"type": "string", "format": "multihash"})

    @classmethod
    def __get_validators__(cls) -> Iterator[Callable[..., Any]]:
        yield cls.validate

    @classmethod
    def validate(cls: Type[_M], value: Any) -> _M:
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            value = bytes.fromhex(value)
        if isinstance(value, bytes):
            func, offset = _read_varint(value, 0)
            length, offset = _read_varint(value, offset)
            digest = value[offset:]
            if len(digest) != length:
                raise ValueError(
                    f"inconsistent length: {len(digest)} != {length}"
                )
            return cls(func, digest)
        raise TypeError(f"unsupported type: {type(value)}")

    def __bytes__(self) -> bytes:
        fp = io.BytesIO()
        _write_varint(self.func, fp)
        _write_varint(len(self.digest), fp)
        fp.write(self.digest)
        return fp.getvalue()

    def __str__(self) -> str:
        return bytes(self).hex()

    def __hash__(self) -> int:
        return hash((self.func, self.digest))
