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


from typing import cast

import apsw
import libtorrent as lt
import pytest

from tests import conftest
from tvaf._internal import resumedb


@pytest.fixture
def conn() -> apsw.Connection:
    result = apsw.Connection(":memory:")
    resumedb.upgrade(result)
    return result


@pytest.fixture(
    params=(conftest.V1, conftest.V2, conftest.HYBRID), ids=lambda v: f"{v.name}"
)
def proto(request: pytest.FixtureRequest) -> conftest.Proto:
    return cast(conftest.Proto, request.param)


@pytest.fixture(params=(True, False), ids=("magnet", "full"))
def magnet(request: pytest.FixtureRequest) -> bool:
    return cast(bool, request.param)


@pytest.fixture
def atp(
    proto: conftest.Proto, magnet: bool, mkatp: conftest.MkAtp
) -> lt.add_torrent_params:
    atp = mkatp(proto=proto)
    assert atp.ti is not None
    if magnet:
        atp = lt.parse_magnet_uri(lt.make_magnet_uri(atp.ti))
    return atp


def test_delete(atp: lt.add_torrent_params, conn: apsw.Connection) -> None:
    resumedb.insert_or_ignore_resume_data(atp, conn)

    resumedb.delete(resumedb.info_hashes(atp), conn)

    atps = list(resumedb.iter_resume_data_from_db(conn))
    assert atps == []
