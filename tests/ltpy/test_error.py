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
from typing import Callable

import libtorrent as lt
import pytest

from tvaf import ltpy


@pytest.mark.parametrize(
    "instantiate", (ltpy.Error, ltpy.LibtorrentError, ltpy.exception_from_error_code)
)
@pytest.mark.parametrize(
    ("value", "result_cls"),
    (
        (
            ltpy.LibtorrentErrorValue.INVALID_TORRENT_HANDLE,
            ltpy.InvalidTorrentHandleError,
        ),
        (
            ltpy.LibtorrentErrorValue.INVALID_SESSION_HANDLE,
            ltpy.InvalidSessionHandleError,
        ),
        (ltpy.LibtorrentErrorValue.DUPLICATE_TORRENT, ltpy.DuplicateTorrentError),
    ),
)
def test_subtypes_libtorrenterror(
    instantiate: Callable[[lt.error_code], ltpy.Error],
    value: int,
    result_cls: type[ltpy.Error],
) -> None:
    ec = lt.error_code(value, lt.libtorrent_category())
    assert isinstance(instantiate(ec), result_cls)


@pytest.mark.parametrize(
    "instantiate", (ltpy.Error, ltpy.OSError, ltpy.exception_from_error_code)
)
# system_category should be the same as generic_category on non-windows
@pytest.mark.parametrize(
    "category",
    (
        lt.generic_category(),
        pytest.param(lt.system_category(), marks=pytest.mark.skipif('os.name == "nt"')),
    ),
)
# Mapping from pep3151
@pytest.mark.parametrize(
    ("value", "result_cls"),
    (
        (errno.EAGAIN, ltpy.BlockingIOError),
        (errno.EALREADY, ltpy.BlockingIOError),
        (errno.EWOULDBLOCK, ltpy.BlockingIOError),
        (errno.EINPROGRESS, ltpy.BlockingIOError),
        (errno.ECHILD, ltpy.ChildProcessError),
        (errno.EPIPE, ltpy.BrokenPipeError),
        (errno.ESHUTDOWN, ltpy.BrokenPipeError),
        (errno.ECONNABORTED, ltpy.ConnectionAbortedError),
        (errno.ECONNREFUSED, ltpy.ConnectionRefusedError),
        (errno.ECONNRESET, ltpy.ConnectionResetError),
        (errno.EEXIST, ltpy.FileExistsError),
        (errno.ENOENT, ltpy.FileNotFoundError),
        (errno.EINTR, ltpy.InterruptedError),
        (errno.EISDIR, ltpy.IsADirectoryError),
        (errno.ENOTDIR, ltpy.NotADirectoryError),
        (errno.EACCES, ltpy.PermissionError),
        (errno.EPERM, ltpy.PermissionError),
        (errno.ESRCH, ltpy.ProcessLookupError),
        (errno.ETIMEDOUT, ltpy.TimeoutError),
    ),
)
def test_subtypes_oserror(
    instantiate: Callable[[lt.error_code], ltpy.Error],
    value: int,
    category: lt.error_category,
    result_cls: type[ltpy.OSError],
) -> None:
    ec = lt.error_code(value, category)
    assert isinstance(instantiate(ec), result_cls)


@pytest.mark.parametrize("instantiate", (ltpy.Error, ltpy.exception_from_error_code))
@pytest.mark.parametrize(
    ("category", "cls"),
    (
        (lt.generic_category(), ltpy.OSError),
        (lt.libtorrent_category(), ltpy.LibtorrentError),
        (lt.upnp_category(), ltpy.UPNPError),
        (lt.http_category(), ltpy.HTTPError),
        (lt.socks_category(), ltpy.SOCKSError),
        (lt.bdecode_category(), ltpy.BDecodeError),
        (lt.i2p_category(), ltpy.I2PError),
    ),
)
def test_subtypes_top_level(
    instantiate: Callable[[lt.error_code], ltpy.Error],
    category: lt.error_category,
    cls: type[ltpy.Error],
) -> None:
    # use a nonce value
    ec = lt.error_code(123, category)
    assert isinstance(instantiate(ec), cls)


# Various WinError values. I can't find symbolic mappings for most of these.
ERROR_WAIT_NO_CHILDREN = 128
ERROR_CHILD_NOT_COMPLETE = 129
ERROR_BROKEN_PIPE = 109
ERROR_FILE_EXISTS = 80
ERROR_ALREADY_EXISTS = 183
ERROR_FILE_NOT_FOUND = 2
ERROR_PATH_NOT_FOUND = 3
ERROR_DIRECTORY = 267
ERROR_ACCESS_DENIED = 5
WSAEWOULDBLOCK = 10035
WSAEINPROGRESS = 10036
WSAEALREADY = 10037
WSAECONNABORTED = 10053
WSAECONNRESET = 10054
WSAECONNREFUSED = 10061
WSAEINTR = 10004
WSAEACCES = 10013
WSAETIMEDOUT = 10060


@pytest.mark.skipif('os.name != "nt"')
@pytest.mark.parametrize(
    "instantiate", (ltpy.Error, ltpy.OSError, ltpy.exception_from_error_code)
)
# This is a combination of pep3151 and cpython's errmap.h
@pytest.mark.parametrize(
    ("value", "result_cls"),
    (
        (WSAEALREADY, ltpy.BlockingIOError),
        (WSAEWOULDBLOCK, ltpy.BlockingIOError),
        (WSAEINPROGRESS, ltpy.BlockingIOError),
        (ERROR_WAIT_NO_CHILDREN, ltpy.ChildProcessError),
        (ERROR_CHILD_NOT_COMPLETE, ltpy.ChildProcessError),
        (ERROR_BROKEN_PIPE, ltpy.BrokenPipeError),
        (WSAECONNABORTED, ltpy.ConnectionAbortedError),
        (WSAECONNREFUSED, ltpy.ConnectionRefusedError),
        (WSAECONNRESET, ltpy.ConnectionResetError),
        (ERROR_FILE_EXISTS, ltpy.FileExistsError),
        (ERROR_ALREADY_EXISTS, ltpy.FileExistsError),
        (ERROR_FILE_NOT_FOUND, ltpy.FileNotFoundError),
        (ERROR_PATH_NOT_FOUND, ltpy.FileNotFoundError),
        (WSAEINTR, ltpy.InterruptedError),
        (ERROR_DIRECTORY, ltpy.NotADirectoryError),
        (ERROR_ACCESS_DENIED, ltpy.PermissionError),
        (WSAEACCES, ltpy.PermissionError),
        (WSAETIMEDOUT, ltpy.TimeoutError),
    ),
)
def test_system_category_windows(
    instantiate: Callable[[lt.error_code], ltpy.Error],
    value: int,
    result_cls: type[ltpy.OSError],
) -> None:
    ec = lt.error_code(value, lt.system_category())
    assert isinstance(instantiate(ec), result_cls)


def test_no_error() -> None:
    ec = lt.error_code(0, lt.generic_category())
    assert ltpy.exception_from_error_code(ec) is None
