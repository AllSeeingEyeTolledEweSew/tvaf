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

import errno
import pathlib

import libtorrent as lt
import pytest

from tvaf import ltpy


def test_real_enoent(tmp_path: pathlib.Path) -> None:
    does_not_exist = tmp_path / "does-not-exist"
    with pytest.raises(FileNotFoundError):
        with ltpy.translate_exceptions():
            lt.torrent_info(str(does_not_exist))


def test_enoent() -> None:
    with pytest.raises(FileNotFoundError):
        with ltpy.translate_exceptions():
            raise RuntimeError(lt.generic_category().message(errno.ENOENT))


def test_duplicate_torrent() -> None:
    with pytest.raises(ltpy.DuplicateTorrentError):
        with ltpy.translate_exceptions():
            raise RuntimeError(
                lt.libtorrent_category().message(
                    ltpy.LibtorrentErrorValue.DUPLICATE_TORRENT
                )
            )
