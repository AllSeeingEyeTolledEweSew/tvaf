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
from __future__ import annotations

import builtins
from collections.abc import Generator
import contextlib
import enum
import errno
import os
from typing import Optional
from typing import TypeVar

import libtorrent as lt

GENERIC_CATEGORY = lt.generic_category()
SYSTEM_CATEGORY = lt.system_category()
LIBTORRENT_CATEGORY = lt.libtorrent_category()
UPNP_CATEGORY = lt.upnp_category()
HTTP_CATEGORY = lt.http_category()
SOCKS_CATEGORY = lt.socks_category()
I2P_CATEGORY = lt.i2p_category()
BDECODE_CATEGORY = lt.bdecode_category()


class LibtorrentErrorValue(enum.IntEnum):

    DUPLICATE_TORRENT = 19
    INVALID_TORRENT_HANDLE = 20
    INVALID_SESSION_HANDLE = 115


class Error(RuntimeError):
    def __new__(cls, ec: lt.error_code):
        use_cls = _CATEGORY_NAME_TO_SUBCLASS.get(ec.category().name(), cls)
        if use_cls is OSError:
            return use_cls.__new__(use_cls, ec)
        if use_cls is LibtorrentError:
            return use_cls.__new__(use_cls, ec)
        return super().__new__(use_cls, ec)  # type: ignore

    def __init__(self, ec: lt.error_code):
        super().__init__(ec.value(), ec.message())
        self.ec = ec
        self.value = ec.value()
        self.category = ec.category()
        self.message = ec.message()

    def __str__(self) -> str:
        return self.message


class OSError(Error, builtins.OSError):
    def __new__(cls, ec: lt.error_code):
        # generic_category uses "portable" errno values, with the same
        # semantics as OSError. libtorrent uses this for errors in
        # platform-independent code.

        # system_category is meant for "system-specific" errors. libtorrent
        # uses these for platform-specific code, including most file i/o code.
        # It uses errno on non-windows, and "WinError" ([WSA]GetLastError)
        # values on windows.

        # We normalize "WinError" values to normal errnos, and use those to
        # dispatch a subclass.
        cat = ec.category()
        if os.name == "nt" and cat == SYSTEM_CATEGORY:
            # TIL: under windows, if the 4th arg is an int, Python will treat
            # it as a "winerror", and will derive an "approximate translation"
            # value for errno, ignoring the 1st arg
            errno_ = builtins.OSError(0, "", None, ec.value()).errno
        elif cat == GENERIC_CATEGORY or (os.name != "nt" and cat == SYSTEM_CATEGORY):
            errno_ = ec.value()
        else:
            # Always instantiate this class directly
            errno_ = 0
        use_cls = _ERRNO_TO_OSERROR.get(errno_, cls)
        # super().__new__, object.__new__, Error.__new__ (with recursion
        # protection) all don't work here. builtins.OSError.__new__ is the only
        # thing that works and I don't understand why.
        # Furthermore, when __new__ and __init__ are overridden in an OSError
        # subclass, then it expects to be initialized using __new__, and
        # super(builtins.OSError, self).__init__.
        args: tuple = ()
        if os.name == "nt" and cat == SYSTEM_CATEGORY:
            args = (0, ec.message(), None, ec.value())
        else:
            args = (ec.value(), ec.message())
        return builtins.OSError.__new__(use_cls, *args)

    def __init__(self, ec: lt.error_code):
        # This does nothing. Why?
        # super(builtins.OSError, self).__init__(*args)
        self.ec = ec
        self.value = ec.value()
        self.category = ec.category()
        self.message = ec.message()

    def __str__(self) -> str:
        return builtins.OSError.__str__(self)


# From pep3151
class BlockingIOError(OSError, builtins.BlockingIOError):
    pass


class ChildProcessError(OSError, builtins.ChildProcessError):
    pass


class ConnectionError(OSError, builtins.ConnectionError):
    pass


class BrokenPipeError(ConnectionError, builtins.BrokenPipeError):
    pass


class ConnectionAbortedError(ConnectionError, builtins.ConnectionAbortedError):
    pass


class ConnectionRefusedError(ConnectionError, builtins.ConnectionRefusedError):
    pass


class ConnectionResetError(ConnectionError, builtins.ConnectionResetError):
    pass


class FileExistsError(OSError, builtins.FileExistsError):
    pass


class FileNotFoundError(OSError, builtins.FileNotFoundError):
    pass


class InterruptedError(OSError, builtins.InterruptedError):
    pass


class IsADirectoryError(OSError, builtins.IsADirectoryError):
    pass


class NotADirectoryError(OSError, builtins.NotADirectoryError):
    pass


class PermissionError(OSError, builtins.PermissionError):
    pass


class ProcessLookupError(OSError, builtins.ProcessLookupError):
    pass


class TimeoutError(OSError, builtins.TimeoutError):
    pass


# ltpy-specific
class CanceledError(OSError):
    pass


class LibtorrentError(Error):
    def __new__(cls, ec: lt.error_code):
        use_cls = cls
        if ec.category() == LIBTORRENT_CATEGORY:
            use_cls = _LIBTORRENT_CODE_TO_SUBCLASS.get(ec.value(), cls)
        return RuntimeError.__new__(use_cls, ec)  # type: ignore


class DuplicateTorrentError(LibtorrentError):
    pass


_C = TypeVar("_C", bound=LibtorrentError)


class InvalidTorrentHandleError(LibtorrentError):
    @classmethod
    def create(cls: type[_C]) -> _C:
        ec = lt.error_code(
            LibtorrentErrorValue.INVALID_TORRENT_HANDLE,
            lt.libtorrent_category(),
        )
        return cls(ec)


class InvalidSessionHandleError(LibtorrentError):
    pass


class UPNPError(Error):
    pass


class HTTPError(Error):
    pass


class SOCKSError(Error):
    pass


class BDecodeError(Error):
    pass


class I2PError(Error):
    pass


# As of libtorrent 1.2.6, error_category.__hash__ functions aren't consistent
# between instances, so we can't use them as dict keys. Use the names as keys
# instead.
_CATEGORY_NAME_TO_SUBCLASS = {
    GENERIC_CATEGORY.name(): OSError,
    SYSTEM_CATEGORY.name(): OSError,
    LIBTORRENT_CATEGORY.name(): LibtorrentError,
    UPNP_CATEGORY.name(): UPNPError,
    HTTP_CATEGORY.name(): HTTPError,
    SOCKS_CATEGORY.name(): SOCKSError,
    I2P_CATEGORY.name(): I2PError,
    BDECODE_CATEGORY.name(): BDecodeError,
}

_LTEV = LibtorrentErrorValue
_LIBTORRENT_CODE_TO_SUBCLASS = {
    _LTEV.DUPLICATE_TORRENT.value: DuplicateTorrentError,
    _LTEV.INVALID_TORRENT_HANDLE.value: InvalidTorrentHandleError,
    _LTEV.INVALID_SESSION_HANDLE.value: InvalidSessionHandleError,
}

_ERRNO_TO_OSERROR = {
    # From pep3151
    errno.EAGAIN: BlockingIOError,
    errno.EALREADY: BlockingIOError,
    errno.EWOULDBLOCK: BlockingIOError,
    errno.EINPROGRESS: BlockingIOError,
    errno.ECHILD: ChildProcessError,
    errno.EPIPE: BrokenPipeError,
    errno.ESHUTDOWN: BrokenPipeError,
    errno.ECONNABORTED: ConnectionAbortedError,
    errno.ECONNREFUSED: ConnectionRefusedError,
    errno.ECONNRESET: ConnectionResetError,
    errno.EEXIST: FileExistsError,
    errno.ENOENT: FileNotFoundError,
    errno.EINTR: InterruptedError,
    errno.EISDIR: IsADirectoryError,
    errno.ENOTDIR: NotADirectoryError,
    errno.EACCES: PermissionError,
    errno.EPERM: PermissionError,
    errno.ESRCH: ProcessLookupError,
    errno.ETIMEDOUT: TimeoutError,
    # ltpy-specific
    errno.ECANCELED: CanceledError,
}


def exception_from_error_code(ec: lt.error_code) -> Optional[Exception]:
    # libtorrent represents non-errors as a non-None error_code object with a
    # value of 0
    if not ec.value():
        return None

    return Error(ec)


def exception_from_alert(alert: lt.alert) -> Optional[Exception]:
    ec = getattr(alert, "error", None)
    if not ec:
        return None
    return exception_from_error_code(ec)


_error_code_msg_lookup: dict[str, dict[lt.error_category, int]] = {}


def _init_error_code_msg_lookup() -> None:
    # There's no way to enumerate all error categories. Check all the ones we
    # know about.
    for category in (
        GENERIC_CATEGORY,
        SYSTEM_CATEGORY,
        LIBTORRENT_CATEGORY,
        BDECODE_CATEGORY,
        HTTP_CATEGORY,
        I2P_CATEGORY,
        SOCKS_CATEGORY,
        UPNP_CATEGORY,
    ):
        # There's no way to enumerate all error codes covered by an
        # error_category. So our strategy is to get the message string for
        # error code #1, and keep incrementing the error code until the
        # messages all look the same.
        last_msg = None
        last_msg_count = 0
        value = 1
        while True:
            msg = lt.error_code(value, category).message()
            _error_code_msg_lookup.setdefault(msg, {}).setdefault(category, value)
            # At least http_category and upnp_category yield messages for
            # unknown error codes like "unknown code 123". We do map these
            # messages, but for stop condition testing we strip the decimal
            # value of the code.
            msg = msg.replace(str(value), "")
            if msg == last_msg:
                last_msg_count += 1
            else:
                last_msg = msg
                last_msg_count = 1
            # If error messages for the last N error codes were the same, we're
            # probably at the end
            if last_msg_count >= 1000:
                break
            # For sanity, stop after a large number of error codes
            if value >= 1000000:
                break
            value += 1


_init_error_code_msg_lookup()


def error_code_from_exception(exc: Exception) -> Optional[lt.error_code]:
    if not isinstance(exc, RuntimeError):
        return None
    msg = str(exc)
    lookup = _error_code_msg_lookup.get(msg)
    if not lookup:
        return None

    # I sampled messages in libtorrent 1.2.6 and found only collisions between
    # generic_category and system_category, and between deprecated
    # libtorrent_category values and their non-deprecated more specific
    # categories.

    # We prefer to use generic_category, as it is meant to contain portable
    # errno values. In particular, cpython's WinError-to-errno mapping is
    # fairly coarse, so mapping errno by message here will probably give better
    # results.

    # We de-prefer libtorrent_category, assuming that some error codes start
    # life as libtorrent_category errors then get specialized into other
    # categories.
    def cat_key(category) -> int:
        return {
            GENERIC_CATEGORY: 0,
            LIBTORRENT_CATEGORY: 2,
        }.get(category, 1)

    items = sorted(lookup.items(), key=lambda item: cat_key(item[0]))
    if not items:
        return None
    category, value = items[0]
    return lt.error_code(value, category)


def _translate_exception(exc: Exception) -> Optional[Exception]:
    if not isinstance(exc, RuntimeError):
        return None
    ec = error_code_from_exception(exc)
    if not ec:
        return None
    return exception_from_error_code(ec)


@contextlib.contextmanager
def translate_exceptions() -> Generator:
    try:
        yield
    except RuntimeError as exc:
        translated = _translate_exception(exc)
        if translated:
            raise translated from exc
        raise


def handle_in_session(handle: lt.torrent_handle, session: lt.session) -> bool:
    with translate_exceptions():
        # DOES block
        return session.find_torrent(handle.info_hash()) == handle


version_info = tuple(int(i) for i in lt.__version__.split("."))
