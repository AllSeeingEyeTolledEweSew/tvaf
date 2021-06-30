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

import base64
import functools
import operator
from typing import List
from typing import Sequence

import pydantic


class TorrentStatus(pydantic.BaseModel):
    pieces: str
    piece_priorities: List[int]


def seq_to_bitfield(seq: Sequence) -> bytes:
    offsets = range(0, len(seq), 8)
    splits = (seq[ofs : ofs + 8] for ofs in offsets)
    enums = (enumerate(spl) for spl in splits)
    bit_splits = ((0x80 >> i if e else 0 for i, e in enum) for enum in enums)
    return bytes(functools.reduce(operator.__or__, b, 0) for b in bit_splits)


def seq_to_bitfield64(seq: Sequence) -> str:
    return base64.b64encode(seq_to_bitfield(seq)).decode("latin-1")
