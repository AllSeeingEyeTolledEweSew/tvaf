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

import libtorrent as lt
import pytest

from tvaf._internal import resumedb


@pytest.fixture
def ti() -> lt.torrent_info:
    fs = lt.file_storage()
    fs.add_file("file.txt", 1024)
    ct = lt.create_torrent(fs)
    ct.set_hash(0, random.randbytes(20))
    return lt.torrent_info(ct.generate())


def test_no_ti(ti: lt.torrent_info) -> None:
    atp = lt.add_torrent_params()
    atp.info_hashes = ti.info_hashes()
    atp.save_path = "test-path"

    info_hashes, resume_data, info = resumedb.split_resume_data(atp)

    assert info_hashes == ti.info_hashes()
    assert lt.read_resume_data(resume_data).save_path == "test-path"
    assert info is None


def test_with_ti(ti: lt.torrent_info) -> None:
    atp = lt.add_torrent_params()
    atp.ti = ti
    atp.save_path = "test-path"

    info_hashes, resume_data, info = resumedb.split_resume_data(atp)

    assert info_hashes == ti.info_hashes()
    assert info == ti.info_section()
    assert lt.read_resume_data(resume_data).save_path == "test-path"
