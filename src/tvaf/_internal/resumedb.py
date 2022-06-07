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
import concurrent.futures
import functools
import logging
from typing import Any
from typing import Awaitable
from typing import Callable
from typing import cast
from typing import Iterable
from typing import Iterator
from typing import NamedTuple
from typing import Optional

import apsw
import dbver
import libtorrent as lt

from tvaf import concurrency
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


def _ih_bytes(info_hashes: lt.info_hash_t) -> tuple[Optional[bytes], Optional[bytes]]:
    return (
        info_hashes.v1.to_bytes() if info_hashes.has_v1() else None,
        info_hashes.v2.to_bytes() if info_hashes.has_v2() else None,
    )


def _log_ih_bytes(info_sha1: Optional[bytes], info_sha256: Optional[bytes]) -> str:
    strs = tuple(b.hex() for b in (info_sha1, info_sha256) if b is not None)
    return f"[{','.join(strs)}]"


def _log_ih(info_hashes: lt.info_hash_t) -> str:
    return _log_ih_bytes(*_ih_bytes(info_hashes))


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


class ResumeData(NamedTuple):
    info_hashes: lt.info_hash_t
    resume_data: bytes
    info: Optional[bytes] = None


def split_resume_data(atp: lt.add_torrent_params) -> ResumeData:
    if atp.ti is None:
        with ltpy.translate_exceptions():
            return ResumeData(
                info_hashes=atp.info_hashes, resume_data=lt.write_resume_data_buf(atp)
            )
    else:
        # It's legal to create an add_torrent_params setting only ti and not
        # info_hashes
        # It would be more efficient to set ti to None and call
        # write_resume_data_buf(), but it turns out the mutation is visible to
        # other alert handlers
        with ltpy.translate_exceptions():
            bdecoded = lt.write_resume_data(atp)
        info = bdecoded.pop(b"info", None)
        with ltpy.translate_exceptions():
            resume_data = lt.bencode(bdecoded)
        if info is not None:
            with ltpy.translate_exceptions():
                info = lt.bencode(info)
        return ResumeData(
            info_hashes=atp.ti.info_hashes(), resume_data=resume_data, info=info
        )


def insert_or_ignore_resume_data(
    info_hashes: lt.info_hash_t, resume_data: bytes, conn: apsw.Connection
) -> None:
    conn.cursor().execute(
        "INSERT OR IGNORE INTO torrent (info_sha1, info_sha256, resume_data) "
        "VALUES (?1, ?2, ?3)",
        (*_ih_bytes(info_hashes), resume_data),
    )


def update_resume_data(
    info_hashes: lt.info_hash_t, resume_data: bytes, conn: apsw.Connection
) -> None:
    # Change OR to AND when https://github.com/arvidn/libtorrent/issues/6913 is fixed
    conn.cursor().execute(
        "UPDATE torrent SET resume_data = ?3 "
        "WHERE (info_sha1 IS ?1) OR (info_sha256 IS ?2)",
        (*_ih_bytes(info_hashes), resume_data),
    )


def update_info_hashes(info_hashes: lt.info_hash_t, conn: apsw.Connection) -> None:
    params = _ih_bytes(info_hashes)
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


def update_info(
    info_hashes: lt.info_hash_t, info: bytes, conn: apsw.Connection
) -> None:
    # Change OR to AND when https://github.com/arvidn/libtorrent/issues/6913 is fixed
    conn.cursor().execute(
        "UPDATE torrent SET info = ?3 "
        "WHERE (info_sha1 IS ?1) OR (info_sha256 IS ?2) "
        "AND (info IS NULL)",
        (*_ih_bytes(info_hashes), info),
    )


def delete(info_hashes: lt.info_hash_t, conn: apsw.Connection) -> None:
    # Change OR to AND when https://github.com/arvidn/libtorrent/issues/6913 is fixed
    conn.cursor().execute(
        "DELETE FROM torrent WHERE (info_sha1 IS ?1) OR (info_sha256 IS ?2)",
        _ih_bytes(info_hashes),
    )


Job = Callable[[apsw.Connection], Any]


class Writer:
    def __init__(self, pool: dbver.Pool[apsw.Connection]) -> None:
        self._pool = pool
        self._maybejobs: asyncio.Queue[Awaitable[Optional[Job]]] = asyncio.Queue()
        self._task: Optional[asyncio.Task] = None
        self._closed = False
        self._executor: Optional[concurrent.futures.ThreadPoolExecutor] = None

    def add_maybe(self, maybejob: Awaitable[Optional[Job]]) -> None:
        assert not self._closed
        self._maybejobs.put_nowait(maybejob)
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    def add(self, func: Callable[..., None], *args: Any) -> None:
        self.add_maybe(concurrency.create_future(functools.partial(func, *args)))

    def _apply(self, jobs: Iterable[Job]) -> None:
        with dbver.begin_pool(self._pool, dbver.IMMEDIATE) as conn:
            dbver.semver_check_breaking(LATEST, upgrade(conn))
            for job in jobs:
                try:
                    job(conn)
                except apsw.Error:
                    _LOG.exception(
                        "dropped resume data update %r",
                        job,
                    )

    async def _step(self) -> None:
        jobs: list[Job] = []
        job = await (await self._maybejobs.get())
        if job is not None:
            jobs.append(job)
        # Batch all available jobs into the next transaction
        while self._maybejobs.qsize() > 0:
            job = await (self._maybejobs.get_nowait())
            if job is not None:
                jobs.append(job)
        if jobs:
            if self._executor is None:
                self._executor = concurrent.futures.ThreadPoolExecutor(
                    max_workers=1, thread_name_prefix="resumedb-writer"
                )
            try:
                await asyncio.get_event_loop().run_in_executor(
                    self._executor, self._apply, jobs
                )
            except apsw.Error:
                _LOG.exception("dropped %s resume data updates", len(jobs))

    async def _run(self) -> None:
        try:
            while not self._closed:
                await self._step()
        except Exception:
            _LOG.exception("fatal error in resume data writer")
            raise
        finally:
            if self._executor is not None:
                await asyncio.to_thread(self._executor.shutdown)
                self._executor = None

    async def close(self) -> None:
        assert not self._closed
        self._closed = True
        if self._task is not None:
            wakeup = concurrency.create_future(None)
            self._maybejobs.put_nowait(wakeup)
            await self._task
            self._task = None
