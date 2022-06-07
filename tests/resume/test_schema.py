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

import apsw
import pytest

from tvaf import resume


@pytest.fixture
def empty_conn() -> apsw.Connection:
    return apsw.Connection(":memory:")


@pytest.fixture
def conn(empty_conn: apsw.Connection) -> apsw.Connection:
    resume.upgrade(empty_conn)
    return empty_conn


def test_upgrade(empty_conn: apsw.Connection) -> None:
    assert resume.get_version(empty_conn) == 0
    new_version = resume.upgrade(empty_conn)
    assert new_version == 1_000_000
    assert resume.get_version(empty_conn) == new_version


def test_insert_v1only(conn: apsw.Connection) -> None:
    conn.cursor().execute(
        "INSERT INTO torrent (info_sha1, resume_data) VALUES (RANDOMBLOB(20), X'00')"
    )


def test_insert_v2only(conn: apsw.Connection) -> None:
    conn.cursor().execute(
        "INSERT INTO torrent (info_sha256, resume_data) VALUES (RANDOMBLOB(32), X'00')"
    )


def test_insert_hybrid(conn: apsw.Connection) -> None:
    conn.cursor().execute(
        "INSERT INTO torrent (info_sha1, info_sha256, resume_data) "
        "VALUES (RANDOMBLOB(20), RANDOMBLOB(32), X'00')",
    )


def test_update_info(conn: apsw.Connection) -> None:
    conn.cursor().execute(
        "INSERT INTO torrent (info_sha1, info_sha256, resume_data) "
        "VALUES (RANDOMBLOB(20), RANDOMBLOB(32), X'00')",
    )
    conn.cursor().execute("UPDATE torrent SET info = X'00'")


def test_insert_info_hash_required(conn: apsw.Connection) -> None:
    with pytest.raises(apsw.ConstraintError):
        conn.cursor().execute("INSERT INTO torrent (info_sha1) VALUES (NULL)")


def test_insert_info_hashes_unique(conn: apsw.Connection) -> None:
    cur = conn.cursor()
    info_sha1, info_sha256 = next(cur.execute("SELECT RANDOMBLOB(20), RANDOMBLOB(32)"))
    cur.execute(
        "INSERT INTO torrent (info_sha1, info_sha256, resume_data) "
        "VALUES (?, ?, X'00')",
        (info_sha1, info_sha256),
    )
    with pytest.raises(apsw.ConstraintError):
        cur.execute(
            "INSERT INTO torrent (info_sha1, resume_data) VALUES (?, X'00')",
            (info_sha1,),
        )
    with pytest.raises(apsw.ConstraintError):
        cur.execute(
            "INSERT INTO torrent (info_sha256, resume_data) VALUES (?, X'00')",
            (info_sha256,),
        )


def test_insert_info_hash_sizes(conn: apsw.Connection) -> None:
    with pytest.raises(apsw.ConstraintError):
        conn.cursor().execute(
            "INSERT INTO torrent (info_sha1, resume_data) VALUES (?, X'00')",
            (b"aaa",),
        )
    with pytest.raises(apsw.ConstraintError):
        conn.cursor().execute(
            "INSERT INTO torrent (info_sha256, resume_data) VALUES (?, X'00')",
            (b"bbb",),
        )


def test_insert_resume_data_required(conn: apsw.Connection) -> None:
    with pytest.raises(apsw.ConstraintError):
        conn.cursor().execute("INSERT INTO torrent (info_sha1) VALUES (RANDOMBLOB(20))")
