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


import libtorrent as lt
import pytest

from tests import conftest
from tvaf._internal import resumedb


@pytest.fixture(
    params=(conftest.V1, conftest.V2, conftest.HYBRID), ids=lambda v: f"{v.name}"
)
def proto(request: pytest.FixtureRequest) -> conftest.Proto:
    return request.param  # type: ignore


@pytest.fixture
def atp(mkatp: conftest.MkAtp, proto: conftest.Proto) -> lt.add_torrent_params:
    return mkatp(proto=proto)


def test_magnet(atp: lt.add_torrent_params) -> None:
    assert atp.ti is not None
    atp = lt.parse_magnet_uri(lt.make_magnet_uri(atp.ti))
    atp.save_path = "test-path"

    split = resumedb.split_resume_data(atp)

    assert split.info_hashes == atp.info_hashes
    assert lt.read_resume_data(split.resume_data).save_path == "test-path"
    assert lt.read_resume_data(split.resume_data).info_hashes == split.info_hashes
    assert split.info is None


def test_full(atp: lt.add_torrent_params) -> None:
    assert atp.ti is not None
    atp.save_path = "test-path"

    split = resumedb.split_resume_data(atp)

    assert split.info_hashes == atp.ti.info_hashes()
    assert split.info == atp.ti.info_section()
    assert lt.read_resume_data(split.resume_data).save_path == "test-path"
    assert lt.read_resume_data(split.resume_data).info_hashes == split.info_hashes
