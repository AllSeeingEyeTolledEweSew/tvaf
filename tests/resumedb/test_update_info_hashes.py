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
import libtorrent as lt
import pytest

from tests import conftest
from tvaf._internal import resumedb

cases = (
    (conftest.V1, conftest.V1),
    (conftest.V1, conftest.HYBRID),
    (conftest.V2, conftest.V2),
    (conftest.V2, conftest.HYBRID),
    (conftest.HYBRID, conftest.HYBRID),
)


@pytest.fixture(params=cases, ids=lambda p: f"{p[0].name}-{p[1].name}")
def protos(request: pytest.FixtureRequest) -> tuple[conftest.Proto, conftest.Proto]:
    magnet_proto, proto = request.param  # type: ignore
    assert (magnet_proto & proto) == magnet_proto
    return (magnet_proto, proto)


@pytest.fixture
def atp(
    protos: tuple[conftest.Proto, conftest.Proto], mkatp: conftest.MkAtp
) -> lt.add_torrent_params:
    _, proto = protos
    return mkatp(proto=proto)


@pytest.fixture
def ti(atp: lt.add_torrent_params) -> lt.torrent_info:
    assert atp.ti is not None
    return atp.ti


@pytest.fixture
def magnet_atp(
    protos: tuple[conftest.Proto, conftest.Proto], atp: lt.add_torrent_params
) -> lt.add_torrent_params:
    magnet_proto, _ = protos
    assert atp.ti is not None
    magnet = lt.parse_magnet_uri(lt.make_magnet_uri(atp.ti))
    if not (magnet_proto & conftest.V1):
        magnet.info_hashes = lt.info_hash_t(magnet.info_hashes.v2)
    elif not (magnet_proto & conftest.V2):
        magnet.info_hashes = lt.info_hash_t(magnet.info_hashes.v1)
    return magnet


@pytest.fixture
def conn(magnet_atp: lt.add_torrent_params) -> apsw.Connection:
    result = apsw.Connection(":memory:")
    resumedb.upgrade(result)
    split = resumedb.split_resume_data(magnet_atp)
    assert split.info is None
    resumedb.insert_or_ignore_resume_data(split.info_hashes, split.resume_data, result)
    return result


def test_update_info(ti: lt.torrent_info, conn: apsw.Connection) -> None:
    resumedb.update_info_hashes(ti.info_hashes(), conn)
    resumedb.update_info(ti.info_hashes(), ti.info_section(), conn)

    atps = list(resumedb.iter_resume_data_from_db(conn))
    assert len(atps) == 1
    (got,) = atps
    assert got.ti is not None
    got_split = resumedb.split_resume_data(got)
    assert got_split.info_hashes == ti.info_hashes()


def test_update_resume_data(
    ti: lt.torrent_info, atp: lt.add_torrent_params, conn: apsw.Connection
) -> None:
    resumedb.update_info_hashes(ti.info_hashes(), conn)
    resumedb.update_info(ti.info_hashes(), ti.info_section(), conn)

    atp.save_path = "expected"
    split = resumedb.split_resume_data(atp)
    resumedb.update_resume_data(split.info_hashes, split.resume_data, conn)

    atps = list(resumedb.iter_resume_data_from_db(conn))
    assert len(atps) == 1
    (got,) = atps
    assert got.save_path == "expected"
    got_split = resumedb.split_resume_data(got)
    assert got_split.info_hashes == split.info_hashes


# Remove invalidated tests after https://github.com/arvidn/libtorrent/issues/6913
@pytest.mark.parametrize("valid", (True, False), ids=("valid", "invalidated"))
def test_delete(ti: lt.torrent_info, conn: apsw.Connection, valid: bool) -> None:
    if valid:
        resumedb.update_info_hashes(ti.info_hashes(), conn)
        resumedb.update_info(ti.info_hashes(), ti.info_section(), conn)

    resumedb.delete(ti.info_hashes(), conn)

    atps = list(resumedb.iter_resume_data_from_db(conn))
    assert atps == []


# Remove invalidated tests after https://github.com/arvidn/libtorrent/issues/6913
@pytest.mark.parametrize("valid", (True, False), ids=("valid", "invalidated"))
def test_update_resume_data_delete(
    ti: lt.torrent_info, atp: lt.add_torrent_params, conn: apsw.Connection, valid: bool
) -> None:
    if valid:
        resumedb.update_info_hashes(ti.info_hashes(), conn)
        resumedb.update_info(ti.info_hashes(), ti.info_section(), conn)

    atp.save_path = "expected"
    split = resumedb.split_resume_data(atp)
    resumedb.update_resume_data(split.info_hashes, split.resume_data, conn)

    resumedb.delete(ti.info_hashes(), conn)

    atps = list(resumedb.iter_resume_data_from_db(conn))
    assert atps == []
