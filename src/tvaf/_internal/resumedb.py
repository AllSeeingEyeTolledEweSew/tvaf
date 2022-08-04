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

import asyncio
from collections.abc import Awaitable
from collections.abc import Iterable
from collections.abc import Iterator
import logging
from typing import Any
from typing import Callable
from typing import cast
from typing import Optional
from typing import TypedDict

import apsw
import dbver
import libtorrent as lt

from tvaf import ltpy

_LOG = logging.getLogger(__name__)

APPLICATION_ID = 690556334
MIGRATIONS = dbver.SemverMigrations[apsw.Connection](application_id=APPLICATION_ID)

LATEST = 1_000_000


@MIGRATIONS.migrates(0, 1_000_000)
def _init_db(conn: apsw.Connection, schema: str) -> None:
    assert schema == "main"
    # NB: nulls are distinct in unique constraints. See https://sqlite.org/nulls.html
    conn.cursor().execute(
        "CREATE TABLE torrent ("
        "info_sha1 BLOB, "
        "info_sha256 BLOB, "
        "resume_data BLOB NOT NULL, "
        "info BLOB, "
        "CHECK (info_sha1 IS NOT NULL OR info_sha256 IS NOT NULL), "
        "CHECK (info_sha1 IS NULL OR LENGTH(info_sha1) = 20), "
        "CHECK (info_sha256 IS NULL OR LENGTH(info_sha256) = 32), "
        "UNIQUE (info_sha1), "
        "UNIQUE (info_sha256))"
    )


get_version = MIGRATIONS.get_format
upgrade = MIGRATIONS.upgrade


def _ih_bytes(ih: lt.info_hash_t) -> tuple[Optional[bytes], Optional[bytes]]:
    return (
        ih.v1.to_bytes() if ih.has_v1() else None,
        ih.v2.to_bytes() if ih.has_v2() else None,
    )


def _log_ih_bytes(info_sha1: Optional[bytes], info_sha256: Optional[bytes]) -> str:
    strs = tuple(b.hex() for b in (info_sha1, info_sha256) if b is not None)
    return f"[{','.join(strs)}]"


def _log_ih(ih: lt.info_hash_t) -> str:
    return _log_ih_bytes(*_ih_bytes(ih))


def iter_resume_data_from_db(conn: apsw.Connection) -> Iterator[lt.add_torrent_params]:
    version = get_version(conn)
    if version == 0:
        return
    dbver.semver_check_breaking(LATEST, version)
    cur = conn.cursor().execute(
        "SELECT info_sha1, info_sha256, resume_data, info FROM torrent"
    )
    for row in cur:
        info_sha1, info_sha256, resume_data, info = cast(
            tuple[Optional[bytes], Optional[bytes], bytes, Optional[bytes]], row
        )
        # NB: certain fields (creation date, creator, comment) live in the torrent_info
        # object at runtime, but are serialized with the resume data. If the b"info"
        # field is empty, the torrent_info won't be created, and these fields will be
        # dropped. We want to deserialize the resume data all at once, rather than
        # deserialize the torrent_info separately.
        info_dict: Optional[Any] = None
        if info is not None:
            try:
                with ltpy.translate_exceptions():
                    info_dict = lt.bdecode(info)
            except ltpy.Error:
                _LOG.exception(
                    "%s parsing info dict", _log_ih_bytes(info_sha1, info_sha256)
                )
        try:
            with ltpy.translate_exceptions():
                bdecoded = lt.bdecode(resume_data)
                if not isinstance(bdecoded, dict):
                    _LOG.error(
                        "%s resume data not a dict",
                        _log_ih_bytes(info_sha1, info_sha256),
                    )
                    continue
                if bdecoded.get(b"info") is None and info_dict is not None:
                    bdecoded[b"info"] = info_dict
                yield lt.read_resume_data(lt.bencode(bdecoded))
        except ltpy.Error:
            _LOG.exception(
                "%s parsing resume data", _log_ih_bytes(info_sha1, info_sha256)
            )


def copy(atp: lt.add_torrent_params) -> lt.add_torrent_params:
    # TODO: use copy constructor when available
    with ltpy.translate_exceptions():
        return lt.read_resume_data(lt.write_resume_data_buf(atp))


def info_hashes(atp: lt.add_torrent_params) -> lt.info_hash_t:
    if atp.ti is not None:
        return atp.ti.info_hashes()
    return atp.info_hashes


def resume_data(atp: lt.add_torrent_params) -> bytes:
    if atp.ti is None:
        with ltpy.translate_exceptions():
            return lt.write_resume_data_buf(atp)
    atp_copy = copy(atp)
    atp_copy.info_hashes = atp.ti.info_hashes()
    atp_copy.ti = None
    with ltpy.translate_exceptions():
        return lt.write_resume_data_buf(atp_copy)


def insert_or_ignore_resume_data(
    atp: lt.add_torrent_params, conn: apsw.Connection
) -> None:
    conn.cursor().execute(
        "INSERT OR IGNORE INTO torrent (info_sha1, info_sha256, resume_data) "
        "VALUES (?1, ?2, ?3)",
        (*_ih_bytes(info_hashes(atp)), resume_data(atp)),
    )


def update_resume_data(atp: lt.add_torrent_params, conn: apsw.Connection) -> None:
    # Change OR to AND when https://github.com/arvidn/libtorrent/issues/6913 is fixed
    conn.cursor().execute(
        "UPDATE torrent SET resume_data = ?3 "
        "WHERE (info_sha1 IS ?1) OR (info_sha256 IS ?2)",
        (*_ih_bytes(info_hashes(atp)), resume_data(atp)),
    )


def update_info_hashes(ih: lt.info_hash_t, conn: apsw.Connection) -> None:
    params = _ih_bytes(ih)
    info_sha1, info_sha256 = params
    if info_sha1 is None or info_sha256 is None:
        return
    conn.cursor().execute(
        "UPDATE torrent SET info_sha1 = ?1 "
        "WHERE (info_sha1 IS NULL) AND (info_sha256 IS ?2)",
        params,
    )
    conn.cursor().execute(
        "UPDATE torrent SET info_sha256 = ?2 "
        "WHERE (info_sha256 IS NULL) AND (info_sha1 IS ?1)",
        params,
    )


def update_info(ti: lt.torrent_info, conn: apsw.Connection) -> None:
    # Change OR to AND when https://github.com/arvidn/libtorrent/issues/6913 is fixed
    conn.cursor().execute(
        "UPDATE torrent SET info = ?3 "
        "WHERE (info_sha1 IS ?1) OR (info_sha256 IS ?2) "
        "AND (info IS NULL)",
        (*_ih_bytes(ti.info_hashes()), ti.info_section()),
    )


def delete(ih: lt.info_hash_t, conn: apsw.Connection) -> None:
    # Change OR to AND when https://github.com/arvidn/libtorrent/issues/6913 is fixed
    conn.cursor().execute(
        "DELETE FROM torrent WHERE (info_sha1 IS ?1) OR (info_sha256 IS ?2)",
        _ih_bytes(ih),
    )


Job = Callable[[apsw.Connection], Any]
Item = Optional[Awaitable[Job]]
Queue = asyncio.Queue[Item]


def _apply(pool: dbver.Pool[apsw.Connection], jobs: Iterable[Job]) -> None:
    with dbver.begin_pool(pool, dbver.IMMEDIATE) as conn:
        conn.setbusyhandler(None)
        dbver.semver_check_breaking(LATEST, upgrade(conn))
        for job in jobs:
            job(conn)


class WriteCoverage(TypedDict, total=False):
    busy: bool


async def write(
    pool: dbver.Pool[apsw.Connection], queue: Queue, *, cov: WriteCoverage = None
) -> None:
    done = False
    while not done:
        # TODO: use a hold-down timer for committing
        item = await queue.get()
        jobs: list[Job] = []
        if item is None:
            done = True
        else:
            jobs.append(await item)
        while jobs:
            # Batch all available jobs into the next transaction
            while not (done or queue.empty()):
                item = queue.get_nowait()
                if item is None:
                    done = True
                else:
                    jobs.append(await item)
            try:
                await asyncio.to_thread(_apply, pool, jobs)
            except apsw.BusyError:
                _LOG.info("resumedb busy, will retry after 200ms")
                await asyncio.sleep(0.2)
                if cov is not None:
                    cov["busy"] = True
            else:
                jobs = []
