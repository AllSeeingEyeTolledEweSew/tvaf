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

import random
import sqlite3
from typing import Any
from typing import cast

import dbver
import libtorrent as lt
import pytest

from tvaf import resume


def normalize(atp: lt.add_torrent_params) -> dict[bytes, Any]:
    bdecoded = lt.write_resume_data(atp)
    # This normalizes any preformatted components
    return cast(dict[bytes, Any], lt.bdecode(lt.bencode(bdecoded)))


@pytest.fixture
def empty_conn() -> dbver.Connection:
    return sqlite3.connect(":memory:", isolation_level=None)


@pytest.fixture
def conn(empty_conn: dbver.Connection) -> dbver.Connection:
    resume.upgrade(empty_conn)
    return empty_conn


@pytest.fixture
def ti() -> lt.torrent_info:
    fs = lt.file_storage()
    fs.add_file("file.txt", 1024)
    ct = lt.create_torrent(fs)
    ct.set_hash(0, random.randbytes(20))
    return lt.torrent_info(ct.generate())


def test_resume_data_external_info(conn: dbver.Connection, ti: lt.torrent_info) -> None:
    orig = lt.add_torrent_params()
    orig.ti = ti
    bdecoded = lt.write_resume_data(orig)
    bdecoded.pop(b"info")
    resume_data = lt.bencode(bdecoded)
    info = ti.info_section()
    info_hashes = ti.info_hashes()
    conn.cursor().execute(
        "INSERT INTO torrent (info_sha1, info_sha256, resume_data, info) "
        "VALUES (?, ?, ?, ?)",
        (info_hashes.v1.to_bytes(), info_hashes.v2.to_bytes(), resume_data, info),
    )

    atps = list(resume.iter_resume_data_from_db(conn))

    assert len(atps) == 1
    assert normalize(atps[0]) == normalize(orig)


def test_bad_resume_data(conn: dbver.Connection) -> None:
    conn.cursor().execute(
        "INSERT INTO torrent (info_sha1, info_sha256, resume_data, info) VALUES "
        "(RANDOMBLOB(20), RANDOMBLOB(32), X'00', NULL)"
    )

    atps = list(resume.iter_resume_data_from_db(conn))

    assert atps == []


def test_good_resume_data_bad_info_dict(
    conn: dbver.Connection, ti: lt.torrent_info
) -> None:
    atp = lt.add_torrent_params()
    atp.ti = ti
    bdecoded = lt.write_resume_data(atp)
    bdecoded.pop(b"info")
    resume_data = lt.bencode(bdecoded)
    conn.cursor().execute(
        "INSERT INTO torrent (info_sha1, info_sha256, resume_data, info) VALUES "
        "(RANDOMBLOB(20), RANDOMBLOB(32), ?, X'00')",
        (resume_data,),
    )

    atps = list(resume.iter_resume_data_from_db(conn))

    assert len(atps) == 1
    assert atps[0].ti is None


def test_empty_database(conn: dbver.Connection) -> None:
    atps = list(resume.iter_resume_data_from_db(conn))
    assert atps == []


def test_invalid_database(empty_conn: dbver.Connection) -> None:
    empty_conn.cursor().execute("PRAGMA application_id = 1")
    with pytest.raises(dbver.VersionError):
        list(resume.iter_resume_data_from_db(empty_conn))
