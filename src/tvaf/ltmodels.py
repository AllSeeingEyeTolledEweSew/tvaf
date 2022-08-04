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

import base64
from collections.abc import Iterator
from collections.abc import Sequence
import datetime
import enum
import functools
import operator
import re
from typing import Any
from typing import Callable
from typing import Optional
from typing import TYPE_CHECKING
from typing import Union

import libtorrent as lt
import pydantic

if TYPE_CHECKING:
    from pydantic.typing import CallableGenerator


class BaseModel(pydantic.BaseModel):
    class Config:
        json_encoders = {bytes: lambda o: base64.b64encode(o).decode()}


class ErrorCode(BaseModel):
    category: str
    value: int
    message: str

    class Config:
        orm_mode = True

        @classmethod
        def getter_dict(cls, ec: lt.error_code) -> dict:
            return {
                "category": ec.category().name(),
                "value": ec.value(),
                "message": ec.message(),
            }


def optional_error_code(ec: Optional[ErrorCode]) -> Optional[ErrorCode]:
    if ec is not None and ec.value == 0:
        return None
    return ec


class Sha1Hash(pydantic.ConstrainedStr):
    to_lower = True
    min_length = 40
    max_length = 40
    regex = re.compile(r"^[a-f0-9]{40}$")

    @classmethod
    def __get_validators__(cls) -> CallableGenerator:
        yield cls.validate_orm
        yield from super().__get_validators__()

    @classmethod
    def validate_orm(cls, value: Any) -> Any:
        if isinstance(value, lt.sha1_hash):
            return str(value)
        return value


class Sha256Hash(pydantic.ConstrainedStr):
    to_lower = True
    min_length = 64
    max_length = 64
    regex = re.compile(r"^[a-f0-9]{64}$")

    @classmethod
    def __get_validators__(cls) -> CallableGenerator:
        yield cls.validate_orm
        yield from super().__get_validators__()

    @classmethod
    def validate_orm(cls, value: Any) -> Any:
        if isinstance(value, lt.sha256_hash):
            return str(value)
        return value


def optional_sha1(sha1: Optional[Sha1Hash]) -> Optional[Sha1Hash]:
    if sha1 == "0" * 40:
        return None
    return sha1


def optional_sha256(sha256: Optional[Sha256Hash]) -> Optional[Sha256Hash]:
    if sha256 == "0" * 64:
        return None
    return sha256


class InfoHashes(BaseModel):
    v1: Optional[Sha1Hash]
    v2: Optional[Sha256Hash]

    class Config:
        orm_mode = True

    _v1_optional = pydantic.validator("v1", allow_reuse=True)(optional_sha1)
    _v2_optional = pydantic.validator("v2", allow_reuse=True)(optional_sha256)


class Base64(pydantic.ConstrainedBytes):
    @classmethod
    def __modify_schema__(cls, field_schema: dict[str, Any]) -> None:
        pydantic.ConstrainedBytes.__modify_schema__(field_schema)
        field_schema.update(type="string", format="byte")

    @classmethod
    def __get_validators__(cls) -> CallableGenerator:
        yield cls.parse_base64
        yield from super().__get_validators__()

    @classmethod
    def parse_base64(cls, value: Any) -> Any:
        if isinstance(value, str):
            return base64.b64decode(value, validate=True)
        return value


class TorrentState(enum.Enum):
    CHECKING_FILES = "checking_files"
    DOWNLOADING_METADATA = "downloading_metadata"
    DOWNLOADING = "downloading"
    FINISHED = "finished"
    SEEDING = "seeding"
    CHECKING_RESUME_DATA = "checking_resume_data"

    @classmethod
    def __get_validators__(cls) -> CallableGenerator:
        yield cls._from_lt

    @classmethod
    def _from_lt(cls, value: Any) -> Any:
        if isinstance(value, int):
            return lt.torrent_status.states.values[value].name  # type: ignore
        return value


class StorageMode(enum.Enum):
    SPARSE = "sparse"
    ALLOCATE = "allocate"

    @classmethod
    def __get_validators__(cls) -> CallableGenerator:
        yield cls._from_lt

    @classmethod
    def _from_lt(cls, value: Any) -> Any:
        if isinstance(value, int):
            return lt.storage_mode_t.values[value].name[13:]  # type: ignore
        return value


def _seq_to_bitfield(seq: Sequence) -> bytes:
    offsets = range(0, len(seq), 8)
    splits = (seq[ofs : ofs + 8] for ofs in offsets)
    enums = (enumerate(spl) for spl in splits)
    bit_splits = ((0x80 >> i if e else 0 for i, e in enum) for enum in enums)
    return bytes(functools.reduce(operator.__or__, b, 0) for b in bit_splits)


def _convert_pieces(value: Any) -> Any:
    if value == []:
        return None
    if isinstance(value, (list, tuple)):
        return _seq_to_bitfield(value)
    raise TypeError()


class TorrentStatus(BaseModel):
    active_duration: datetime.timedelta
    added_time: int
    all_time_download: int
    all_time_upload: int
    announcing_to_dht: bool
    announcing_to_lsd: bool
    announcing_to_trackers: bool
    block_size: int
    completed_time: int
    connect_candidates: int
    connections_limit: int
    current_tracker: str
    distributed_copies: float
    distributed_fraction: int
    distributed_full_copies: int
    down_bandwidth_queue: int
    download_payload_rate: int
    download_rate: int
    errc: ErrorCode
    error_file: int
    finished_duration: datetime.timedelta
    flags: int
    has_incoming: bool
    has_metadata: bool
    info_hashes: InfoHashes
    is_finished: bool
    is_seeding: bool
    last_download: Optional[datetime.datetime]
    last_seen_complete: int
    last_upload: Optional[datetime.datetime]
    list_peers: int
    list_seeds: int
    moving_storage: bool
    name: str
    need_save_resume: bool
    next_announce: datetime.timedelta
    num_complete: int
    num_connections: int
    num_incomplete: int
    num_peers: int
    num_pieces: int
    num_seeds: int
    num_uploads: int
    pieces: Optional[Base64]
    progress: float
    progress_ppm: int
    queue_position: int
    save_path: str
    seed_rank: int
    seeding_duration: datetime.timedelta
    state: TorrentState
    storage_mode: StorageMode
    # torrent_file: Optional[torrent_info]
    total_done: int
    total_download: int
    total_failed_bytes: int
    total_payload_download: int
    total_payload_upload: int
    total_redundant_bytes: int
    total_upload: int
    total_wanted: int
    total_wanted_done: int
    up_bandwidth_queue: int
    upload_payload_rate: int
    upload_rate: int
    uploads_limit: int
    verified_pieces: Optional[Base64]

    _errc = pydantic.validator("errc", allow_reuse=True)(optional_error_code)

    _pieces = pydantic.validator("pieces", pre=True, allow_reuse=True)(_convert_pieces)
    _verified_pieces = pydantic.validator(
        "verified_pieces", pre=True, allow_reuse=True
    )(_convert_pieces)

    class Config:
        orm_mode = True


class HexBase(bytes):
    regex = re.compile(r"[0-9a-f]*$")
    bits = 0

    @classmethod
    def __modify_schema__(cls, field_schema: dict[str, Any]) -> None:
        length = cls.bits // 4
        field_schema.update(
            {
                "type": "string",
                "format": "hex",
                "pattern": cls.regex.pattern,
                "minLength": length,
                "maxLength": length,
            }
        )

    @classmethod
    def __get_validators__(cls) -> Iterator[Callable[..., Any]]:
        yield cls.validate

    @classmethod
    def validate(cls, value: Any) -> bytes:
        if isinstance(value, bytes):
            return value
        if isinstance(value, bytearray):
            return bytes(value)
        if isinstance(value, str):
            length = cls.bits // 4
            if len(value) < length:
                raise pydantic.AnyStrMinLengthError(limit_value=length)
            if len(value) > length:
                raise pydantic.AnyStrMaxLengthError(limit_value=length)
            if not cls.regex.match(value):
                raise pydantic.StrRegexError(pattern=cls.regex.pattern)
            return bytes.fromhex(value)
        raise pydantic.BytesError()


class Hex160(HexBase):
    bits = 160


def hash_from_digest(digest: bytes) -> Union[lt.sha1_hash, lt.sha256_hash]:
    if len(digest) == 20:
        return lt.sha1_hash(digest)
    if len(digest) == 32:
        return lt.sha256_hash(digest)
    raise ValueError(digest)


def info_hashes_from_digest(digest: bytes) -> lt.info_hash_t:
    return lt.info_hash_t(hash_from_digest(digest))
