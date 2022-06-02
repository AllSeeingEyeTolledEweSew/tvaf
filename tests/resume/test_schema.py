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

import sqlite3

import dbver
import pytest

from tvaf import resume


@pytest.fixture
def empty_conn() -> dbver.Connection:
    return sqlite3.connect(":memory:", isolation_level=None)


@pytest.fixture
def conn(empty_conn: dbver.Connection) -> dbver.Connection:
    resume.upgrade(empty_conn)
    return empty_conn


def test_upgrade(empty_conn: sqlite3.Connection) -> None:
    assert resume.get_version(empty_conn) == 0
    new_version = resume.upgrade(empty_conn)
    assert new_version == 1_000_000
    assert resume.get_version(empty_conn) == new_version


def test_insert_v1only(conn: dbver.Connection) -> None:
    conn.cursor().execute(
        "INSERT INTO torrent (info_sha1, resume_data) " "VALUES (RANDOMBLOB(20), X'00')"
    )


def test_insert_v2only(conn: dbver.Connection) -> None:
    conn.cursor().execute(
        "INSERT INTO torrent (info_sha256, resume_data) "
        "VALUES (RANDOMBLOB(32), X'00')"
    )


def test_insert_hybrid(conn: dbver.Connection) -> None:
    conn.cursor().execute(
        "INSERT INTO torrent (info_sha1, info_sha256, resume_data) "
        "VALUES (RANDOMBLOB(20), RANDOMBLOB(32), X'00')",
    )


def test_update_info(conn: dbver.Connection) -> None:
    conn.cursor().execute(
        "INSERT INTO torrent (info_sha1, info_sha256, resume_data) "
        "VALUES (RANDOMBLOB(20), RANDOMBLOB(32), X'00')",
    )
    conn.cursor().execute("UPDATE torrent SET info = X'00'")


def test_insert_info_hash_required(conn: dbver.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        conn.cursor().execute("INSERT INTO torrent (info_sha1) VALUES (NULL)")


def test_insert_info_hashes_unique(conn: dbver.Connection) -> None:
    info_sha1, info_sha256 = (
        conn.cursor().execute("SELECT RANDOMBLOB(20), RANDOMBLOB(32)").fetchone()
    )
    conn.cursor().execute(
        "INSERT INTO torrent (info_sha1, info_sha256, resume_data) "
        "VALUES (?, ?, X'00')",
        (info_sha1, info_sha256),
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.cursor().execute(
            "INSERT INTO torrent (info_sha1, resume_data) VALUES (?, X'00')",
            (info_sha1,),
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.cursor().execute(
            "INSERT INTO torrent (info_sha256, resume_data) VALUES (?, X'00')",
            (info_sha256,),
        )


def test_insert_info_hash_sizes(conn: dbver.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        conn.cursor().execute(
            "INSERT INTO torrent (info_sha1, resume_data) VALUES (?, X'00')",
            (b"aaa",),
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.cursor().execute(
            "INSERT INTO torrent (info_sha256, resume_data) VALUES (?, X'00')",
            (b"bbb",),
        )


def test_insert_resume_data_required(conn: dbver.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        conn.cursor().execute("INSERT INTO torrent (info_sha1) VALUES (RANDOMBLOB(20))")
