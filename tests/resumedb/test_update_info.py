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
from typing import Optional

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


@pytest.fixture
def atp(proto: conftest.Proto, mkatp: conftest.MkAtp) -> lt.add_torrent_params:
    return mkatp(proto=proto)


def assert_ti_equal(a: Optional[lt.torrent_info], b: Optional[lt.torrent_info]) -> None:
    if a is None:
        assert b is None
    else:
        assert b is not None
        assert a.info_section() == b.info_section()


def test_update(atp: lt.add_torrent_params, conn: apsw.Connection) -> None:
    atp.save_path = "expected"
    resumedb.insert_or_ignore_resume_data(atp, conn)

    assert atp.ti is not None
    resumedb.update_info(atp.ti, conn)

    atps = list(resumedb.iter_resume_data_from_db(conn))
    assert len(atps) == 1
    (got,) = atps
    assert got.save_path == "expected"
    assert resumedb.info_hashes(got) == resumedb.info_hashes(atp)
    assert got.ti is not None
    assert_ti_equal(got.ti, atp.ti)
