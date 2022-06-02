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
import dataclasses
import logging
from typing import Any
from typing import Awaitable
from typing import cast
from typing import Iterable
from typing import Iterator
from typing import Optional

import dbver
import libtorrent as lt

from tvaf import concurrency
from tvaf import ltpy

_LOG = logging.getLogger(__name__)

APPLICATION_ID = 690556334
MIGRATIONS = dbver.SemverMigrations[dbver.Connection](application_id=APPLICATION_ID)

LATEST = 1_000_000


@MIGRATIONS.migrates(0, 1_000_000)
def _init_db(conn: dbver.Connection, schema: str) -> None:
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


def iter_resume_data_from_db(conn: dbver.Connection) -> Iterator[lt.add_torrent_params]:
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


def _changes(conn: dbver.Connection) -> int:
    cur = conn.cursor()
    (changes,) = cast(tuple[int], cur.execute("SELECT CHANGES()").fetchone())
    return changes


@dataclasses.dataclass()
class Job:
    info_hashes: lt.info_hash_t

    def __call__(self, conn: dbver.Connection) -> None:
        raise NotImplementedError


@dataclasses.dataclass()
class WriteResumeData(Job):
    resume_data: bytes
    overwrite: bool = True

    def __call__(self, conn: dbver.Connection) -> None:
        # Poor man's upsert. Change this when we can use apsw
        params = (*_ih_bytes(self.info_hashes), self.resume_data)
        conn.cursor().execute(
            "INSERT OR IGNORE INTO torrent (info_sha1, info_sha256, resume_data) "
            "VALUES (?1, ?2, ?3)",
            params,
        )
        changes = _changes(conn)
        if self.overwrite and not changes:
            conn.cursor().execute(
                "UPDATE torrent SET resume_data = ?3 "
                "WHERE info_sha1 IS ?1 AND info_sha256 IS ?2",
                params,
            )
        _LOG.debug(
            "%s %s resume data",
            _log_ih(self.info_hashes),
            "wrote" if changes or self.overwrite else "skipped writing",
        )


@dataclasses.dataclass()
class WriteInfo(Job):
    info: bytes

    def __call__(self, conn: dbver.Connection) -> None:
        info_hashes = _ih_bytes(self.info_hashes)
        # Update info-hashes, in case of a magnet link to a hybrid torrent which was
        # added with only one hash
        if None not in info_hashes:
            # NB: this could violate SQL-level constraints in theory. We rely on the
            # fact that libtorrent's internal indexes follow the same constraints. In
            # particular if two magnet-link torrents are added, using the v1 and v2
            # hashes of the same hybrid torrent, then when they receive metadata, BOTH
            # will error out, and neither will emit metadata_received_alert
            conn.cursor().execute(
                "UPDATE torrent SET info_sha1 = ?1 WHERE (info_sha1 IS NULL) "
                "AND (info_sha256 IS ?2)",
                info_hashes,
            )
            if _LOG.isEnabledFor(logging.DEBUG):
                changes = _changes(conn)
                _LOG.debug(
                    "%s %s sha1 hash",
                    _log_ih(self.info_hashes),
                    "updated" if changes else "skipped updating",
                )
            conn.cursor().execute(
                "UPDATE torrent SET info_sha256 = ?2 WHERE (info_sha1 IS NULL) "
                "AND (info_sha1 IS ?1)",
                info_hashes,
            )
            if _LOG.isEnabledFor(logging.DEBUG):
                changes = _changes(conn)
                _LOG.debug(
                    "%s %s sha256 hash",
                    _log_ih(self.info_hashes),
                    "updated" if changes else "skipped updating",
                )
        conn.cursor().execute(
            "UPDATE torrent SET info = ?3 "
            "WHERE (info_sha1 IS ?1) AND (info_sha256 IS ?2) "
            "AND (info IS NULL)",
            (*info_hashes, self.info),
        )
        if _LOG.isEnabledFor(logging.DEBUG):
            changes = _changes(conn)
            _LOG.debug(
                "%s %s info section",
                _log_ih(self.info_hashes),
                "wrote" if changes else "skipped writing",
            )


@dataclasses.dataclass()
class Delete(Job):
    def __call__(self, conn: dbver.Connection) -> None:
        conn.cursor().execute(
            "DELETE FROM torrent WHERE (info_sha1 IS ?1) AND (info_sha256 IS ?2)",
            _ih_bytes(self.info_hashes),
        )
        changes = _changes(conn)
        if changes:
            _LOG.debug("%s deleted resume data", _log_ih(self.info_hashes))
        else:
            _LOG.warning(
                "%s wanted to delete resume data, but not found. this may be a bug!",
                _log_ih(self.info_hashes),
            )


class Writer:
    def __init__(self, pool: dbver.Pool) -> None:
        self._pool = pool
        self._maybejobs: asyncio.Queue[Awaitable[Optional[Job]]] = asyncio.Queue()
        self._task: Optional[asyncio.Task] = None
        self._closed = False
        self._executor: Optional[concurrent.futures.ThreadPoolExecutor] = None

    def add(self, maybejob: Awaitable[Optional[Job]]) -> None:
        assert not self._closed
        self._maybejobs.put_nowait(maybejob)
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    def _apply(self, jobs: Iterable[Job]) -> None:
        with dbver.begin_pool(self._pool, dbver.IMMEDIATE) as conn:
            dbver.semver_check_breaking(LATEST, upgrade(conn))
            for job in jobs:
                try:
                    job(conn)
                except dbver.Errors:
                    _LOG.exception(
                        "%s dropped resume data update %r",
                        _log_ih(job.info_hashes),
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
            except dbver.Errors:
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
