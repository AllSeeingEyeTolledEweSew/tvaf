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
import functools
import pathlib
from typing import Any
from typing import Awaitable
from typing import Callable
from typing import Iterator
from typing import Optional

import apsw
import dbver
import libtorrent as lt
import pytest

from tests import conftest
from tests import lib
from tvaf import concurrency
from tvaf._internal import resumedb


@pytest.fixture
def conn_factory(tmp_path: pathlib.Path) -> Callable[[], apsw.Connection]:
    def mk_conn() -> apsw.Connection:
        path = tmp_path / "tmp.db"
        conn = apsw.Connection(str(path))
        conn.cursor().execute("PRAGMA journal_mode = WAL")
        return conn

    return mk_conn


@pytest.fixture
def pool(conn_factory: Callable[[], apsw.Connection]) -> dbver.Pool[apsw.Connection]:
    return dbver.null_pool(conn_factory)


@pytest.fixture
def conn(pool: dbver.Pool[apsw.Connection]) -> Iterator[apsw.Connection]:
    with pool() as local_conn:
        yield local_conn


@pytest.fixture(
    params=(conftest.V1, conftest.V2, conftest.HYBRID), ids=lambda v: f"{v.name}"
)
def proto(request: pytest.FixtureRequest) -> conftest.Proto:
    return request.param  # type: ignore


@pytest.fixture
def atp(proto: conftest.Proto, mkatp: conftest.MkAtp) -> lt.add_torrent_params:
    return mkatp(proto=proto)


@pytest.fixture
async def queue() -> resumedb.Queue:
    return asyncio.Queue()


@pytest.fixture
def cov() -> resumedb.WriteCoverage:
    return resumedb.WriteCoverage()


@pytest.fixture
async def task(
    pool: dbver.Pool[apsw.Connection],
    queue: resumedb.Queue,
    cov: resumedb.WriteCoverage,
) -> asyncio.Task:
    return asyncio.create_task(resumedb.write(pool, queue, cov=cov))


def _put(queue: resumedb.Queue, func: Callable[..., Any], *args: Any) -> None:
    queue.put_nowait(concurrency.create_future(functools.partial(func, *args)))


@pytest.fixture
def get_atps(
    conn: apsw.Connection,
) -> Callable[[], Awaitable[list[lt.add_torrent_params]]]:
    def inner_in_thread() -> list[lt.add_torrent_params]:
        return list(resumedb.iter_resume_data_from_db(conn))

    async def inner() -> list[lt.add_torrent_params]:
        return await asyncio.to_thread(inner_in_thread)

    return inner


# TODO: parametrize concurrency somehow?
async def test_write(
    task: asyncio.Task,
    queue: resumedb.Queue,
    atp: lt.add_torrent_params,
    get_atps: Callable[[], Awaitable[list[lt.add_torrent_params]]],
) -> None:
    _put(queue, resumedb.insert_or_ignore_resume_data, atp)
    got_atps: Optional[list[lt.add_torrent_params]] = None
    async for _ in lib.aloop_until_timeout(5, msg="atp write"):
        got_atps = await get_atps()
        if got_atps:
            break
    assert got_atps is not None
    assert len(got_atps) == 1
    assert resumedb.info_hashes(got_atps[0]) == resumedb.info_hashes(atp)
    queue.put_nowait(None)
    await asyncio.wait_for(task, 5)


async def test_add_jobs_after_cancel(
    task: asyncio.Task,
    queue: resumedb.Queue,
    atp: lt.add_torrent_params,
    get_atps: Callable[[], Awaitable[list[lt.add_torrent_params]]],
) -> None:
    queue.put_nowait(None)
    _put(queue, resumedb.insert_or_ignore_resume_data, atp)
    await asyncio.wait_for(task, 5)
    got_atps = await get_atps()
    assert got_atps == []


async def test_batch(
    task: asyncio.Task,
    queue: resumedb.Queue,
    mkatp: conftest.MkAtp,
    get_atps: Callable[[], Awaitable[list[lt.add_torrent_params]]],
) -> None:
    atp1, atp2, atp3 = mkatp(), mkatp(), mkatp()
    _put(queue, resumedb.insert_or_ignore_resume_data, atp1)
    _put(queue, resumedb.insert_or_ignore_resume_data, atp2)
    queue.put_nowait(None)
    _put(queue, resumedb.insert_or_ignore_resume_data, atp3)
    await asyncio.wait_for(task, 5)
    got_atps = await get_atps()
    got_hashes = {resumedb.info_hashes(a) for a in got_atps}
    expected_hashes = {resumedb.info_hashes(a) for a in (atp1, atp2)}
    assert got_hashes == expected_hashes


async def test_busyerror(
    task: asyncio.Task,
    cov: resumedb.WriteCoverage,
    queue: resumedb.Queue,
    conn: apsw.Connection,
    atp: lt.add_torrent_params,
    get_atps: Callable[[], Awaitable[list[lt.add_torrent_params]]],
) -> None:
    await asyncio.to_thread(conn.cursor().execute, "BEGIN IMMEDIATE")
    _put(queue, resumedb.insert_or_ignore_resume_data, atp)
    async for _ in lib.aloop_until_timeout(5, msg="busy"):
        if cov.get("busy"):
            break
        await asyncio.sleep(0)
    await asyncio.to_thread(conn.cursor().execute, "ROLLBACK")
    got_atps: Optional[list[lt.add_torrent_params]] = None
    async for _ in lib.aloop_until_timeout(5, msg="atp write"):
        got_atps = await get_atps()
        if got_atps:
            break
    assert got_atps is not None
    assert len(got_atps) == 1
    assert resumedb.info_hashes(got_atps[0]) == resumedb.info_hashes(atp)
    queue.put_nowait(None)
    await asyncio.wait_for(task, 5)
