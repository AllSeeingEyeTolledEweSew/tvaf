from tvaf import ltpy
import os
import errno
import unittest
import libtorrent as lt


class TestExceptionSubtypeInstantiation(unittest.TestCase):

    def test_error_to_libtorent_error(self):
        def func(value):
            return ltpy.Error(lt.error_code(value, lt.libtorrent_category()))

        self.assertIsInstance(func(999), ltpy.LibtorrentError)
        self.assertIsInstance(func(ltpy.LibtorrentErrorValue.INVALID_TORRENT_HANDLE),
                ltpy.InvalidTorrentHandleError)
        self.assertIsInstance(func(ltpy.LibtorrentErrorValue.INVALID_SESSION_HANDLE),
                ltpy.InvalidSessionHandleError)
        self.assertIsInstance(func(ltpy.LibtorrentErrorValue.DUPLICATE_TORRENT),
                ltpy.DuplicateTorrentError)

    def test_error_to_oserror(self):
        def func(value):
            return ltpy.Error(lt.error_code(value, lt.generic_category()))

        # Mapping from pep3151
        self.assertIsInstance(func(errno.EAGAIN),
                ltpy.BlockingIOError)
        self.assertIsInstance(func(errno.EALREADY),
                ltpy.BlockingIOError)
        self.assertIsInstance(func(errno.EWOULDBLOCK),
                ltpy.BlockingIOError)
        self.assertIsInstance(func(errno.EINPROGRESS),
                ltpy.BlockingIOError)
        self.assertIsInstance(func(errno.ECHILD),
                ltpy.ChildProcessError)
        self.assertIsInstance(func(errno.EPIPE),
                ltpy.BrokenPipeError)
        self.assertIsInstance(func(errno.ESHUTDOWN),
                ltpy.BrokenPipeError)
        self.assertIsInstance(func(errno.ECONNABORTED),
                ltpy.ConnectionAbortedError)
        self.assertIsInstance(func(errno.ECONNREFUSED),
                ltpy.ConnectionRefusedError)
        self.assertIsInstance(func(errno.ECONNRESET),
                ltpy.ConnectionResetError)
        self.assertIsInstance(func(errno.EEXIST),
                ltpy.FileExistsError)
        self.assertIsInstance(func(errno.ENOENT),
                ltpy.FileNotFoundError)
        self.assertIsInstance(func(errno.EINTR),
                ltpy.InterruptedError)
        self.assertIsInstance(func(errno.EISDIR),
                ltpy.IsADirectoryError)
        self.assertIsInstance(func(errno.ENOTDIR),
                ltpy.NotADirectoryError)
        self.assertIsInstance(func(errno.EACCES),
                ltpy.PermissionError)
        self.assertIsInstance(func(errno.EPERM),
                ltpy.PermissionError)
        self.assertIsInstance(func(errno.ESRCH),
                ltpy.ProcessLookupError)
        self.assertIsInstance(func(errno.ETIMEDOUT),
                ltpy.TimeoutError)

    def test_error_to_upnp_error(self):
        def func(value):
            return ltpy.Error(lt.error_code(value, lt.upnp_category()))

        self.assertIsInstance(func(1), ltpy.UPNPError)

    def test_error_to_http_error(self):
        def func(value):
            return ltpy.Error(lt.error_code(value, lt.http_category()))

        self.assertIsInstance(func(1), ltpy.HTTPError)
        
    def test_error_to_socks_error(self):
        def func(value):
            return ltpy.Error(lt.error_code(value, lt.socks_category()))

        self.assertIsInstance(func(1), ltpy.SOCKSError)

    def test_error_to_bdecode_error(self):
        def func(value):
            return ltpy.Error(lt.error_code(value, lt.bdecode_category()))

        self.assertIsInstance(func(1), ltpy.BDecodeError)

    def test_error_to_i2p_error(self):
        def func(value):
            return ltpy.Error(lt.error_code(value, lt.i2p_category()))

        self.assertIsInstance(func(1), ltpy.I2PError)

    def test_libtorrent_error(self):
        def func(value):
            return ltpy.LibtorrentError(lt.error_code(value,
                lt.libtorrent_category()))

        self.assertIsInstance(func(999),
                ltpy.LibtorrentError)
        self.assertIsInstance(func(ltpy.LibtorrentErrorValue.DUPLICATE_TORRENT),
                ltpy.DuplicateTorrentError)
        self.assertIsInstance(func(ltpy.LibtorrentErrorValue.INVALID_TORRENT_HANDLE),
                ltpy.InvalidTorrentHandleError)
        self.assertIsInstance(func(ltpy.LibtorrentErrorValue.INVALID_SESSION_HANDLE),
                ltpy.InvalidSessionHandleError)

        # Test construction with wrong category
        self.assertIsInstance(ltpy.LibtorrentError(lt.error_code(errno.ENOENT,
            lt.generic_category())),
                ltpy.LibtorrentError)

    def _test_oserror_from_errno(self, category):
        def func(value):
            return ltpy.OSError(lt.error_code(value, category))

        # Try invalid errno
        self.assertIsInstance(func(-1), ltpy.OSError)

        # Mapping from pep3151
        self.assertIsInstance(func(errno.EAGAIN),
                ltpy.BlockingIOError)
        self.assertIsInstance(func(errno.EALREADY),
                ltpy.BlockingIOError)
        self.assertIsInstance(func(errno.EWOULDBLOCK),
                ltpy.BlockingIOError)
        self.assertIsInstance(func(errno.EINPROGRESS),
                ltpy.BlockingIOError)
        self.assertIsInstance(func(errno.ECHILD),
                ltpy.ChildProcessError)
        self.assertIsInstance(func(errno.EPIPE),
                ltpy.BrokenPipeError)
        self.assertIsInstance(func(errno.ESHUTDOWN),
                ltpy.BrokenPipeError)
        self.assertIsInstance(func(errno.ECONNABORTED),
                ltpy.ConnectionAbortedError)
        self.assertIsInstance(func(errno.ECONNREFUSED),
                ltpy.ConnectionRefusedError)
        self.assertIsInstance(func(errno.ECONNRESET),
                ltpy.ConnectionResetError)
        self.assertIsInstance(func(errno.EEXIST),
                ltpy.FileExistsError)
        self.assertIsInstance(func(errno.ENOENT),
                ltpy.FileNotFoundError)
        self.assertIsInstance(func(errno.EINTR),
                ltpy.InterruptedError)
        self.assertIsInstance(func(errno.EISDIR),
                ltpy.IsADirectoryError)
        self.assertIsInstance(func(errno.ENOTDIR),
                ltpy.NotADirectoryError)
        self.assertIsInstance(func(errno.EACCES),
                ltpy.PermissionError)
        self.assertIsInstance(func(errno.EPERM),
                ltpy.PermissionError)
        self.assertIsInstance(func(errno.ESRCH),
                ltpy.ProcessLookupError)
        self.assertIsInstance(func(errno.ETIMEDOUT),
                ltpy.TimeoutError)

    def test_oserror_generic(self):
        self._test_oserror_from_errno(lt.generic_category())

        # Test construction with wrong category
        self.assertIsInstance(ltpy.OSError(lt.error_code(-1,
            lt.libtorrent_category())),
                ltpy.OSError)

    def test_oserror_system(self):
        if os.name == "nt":
            self._test_oserror_windows()
        else:
            self._test_oserror_nonwindows()

    def _test_oserror_windows(self):
        def func(value):
            return ltpy.OSError(lt.error_code(value, lt.system_category()))

        # Try invalid WinError
        self.assertIsInstance(func(-1), ltpy.OSError)

        # This is a combination of pep3151 and cpython's errmap.h.

        # I can't find any symbolic mappings for most WinErrors.
        ERROR_WAIT_NO_CHILDREN = 128
        ERROR_CHILD_NOT_COMPLETE = 129
        ERROR_BROKEN_PIPE = 109
        ERROR_FILE_EXISTS = 80
        ERROR_ALREADY_EXISTS = 183
        ERROR_FILE_NOT_FOUND = 2
        ERROR_PATH_NOT_FOUND = 3
        ERROR_DIRECTORY = 267
        ERROR_ACCESS_DENIED = 5

        self.assertIsInstance(func(errno.WSAEALREADY),
                ltpy.BlockingIOError)
        self.assertIsInstance(func(errno.WSAEWOULDBLOCK),
                ltpy.BlockingIOError)
        self.assertIsInstance(func(errno.WSAEINPROGRESS),
                ltpy.BlockingIOError)
        self.assertIsInstance(func(ERROR_WAIT_NO_CHILDREN), ltpy.ChildProcessError)
        self.assertIsInstance(func(ERROR_CHILD_NOT_COMPLETE), ltpy.ChildProcessError)
        self.assertIsInstance(func(ERROR_BROKEN_PIPE), ltpy.BrokenPipeError)
        self.assertIsInstance(func(errno.WSAECONNABORTED),
                ltpy.ConnectionAbortedError)
        self.assertIsInstance(func(errno.WSAECONNREFUSED),
                ltpy.ConnectionRefusedError)
        self.assertIsInstance(func(errno.WSAECONNRESET),
                ltpy.ConnectionResetError)
        self.assertIsInstance(func(ERROR_FILE_EXISTS), ltpy.FileExistsError)
        self.assertIsInstance(func(ERROR_ALREADY_EXISTS), ltpy.FileExistsError)
        self.assertIsInstance(func(ERROR_FILE_NOT_FOUND),
                ltpy.FileNotFoundError)
        self.assertIsInstance(func(ERROR_PATH_NOT_FOUND),
                ltpy.FileNotFoundError)
        self.assertIsInstance(func(errno.WSAEINTR), ltpy.InterruptedError)
        self.assertIsInstance(func(ERROR_DIRECTORY), ltpy.NotADirectoryError)
        self.assertIsInstance(func(ERROR_ACCESS_DENIED),
                ltpy.PermissionError)
        self.assertIsInstance(func(errno.WSAEACCES),
                ltpy.PermissionError)
        self.assertIsInstance(func(errno.WSAETIMEDOUT),
                ltpy.TimeoutError)

    def _test_oserror_nonwindows(self):
        self._test_oserror_from_errno(lt.system_category())


class TestExceptionFromErrorCode(unittest.TestCase):

    def test_libtorent_error(self):
        def func(value):
            return ltpy.exception_from_error_code(lt.error_code(value,
                    lt.libtorrent_category()))

        self.assertIsInstance(func(999), ltpy.LibtorrentError)
        self.assertIsInstance(func(ltpy.LibtorrentErrorValue.INVALID_TORRENT_HANDLE),
                ltpy.InvalidTorrentHandleError)
        self.assertIsInstance(func(ltpy.LibtorrentErrorValue.INVALID_SESSION_HANDLE),
                ltpy.InvalidSessionHandleError)
        self.assertIsInstance(func(ltpy.LibtorrentErrorValue.DUPLICATE_TORRENT),
                ltpy.DuplicateTorrentError)

    def test_generic_category(self):
        def func(value):
            return ltpy.exception_from_error_code(lt.error_code(value,
                    lt.generic_category()))

        # Mapping from pep3151
        self.assertIsInstance(func(errno.EAGAIN),
                ltpy.BlockingIOError)
        self.assertIsInstance(func(errno.EALREADY),
                ltpy.BlockingIOError)
        self.assertIsInstance(func(errno.EWOULDBLOCK),
                ltpy.BlockingIOError)
        self.assertIsInstance(func(errno.EINPROGRESS),
                ltpy.BlockingIOError)
        self.assertIsInstance(func(errno.ECHILD),
                ltpy.ChildProcessError)
        self.assertIsInstance(func(errno.EPIPE),
                ltpy.BrokenPipeError)
        self.assertIsInstance(func(errno.ESHUTDOWN),
                ltpy.BrokenPipeError)
        self.assertIsInstance(func(errno.ECONNABORTED),
                ltpy.ConnectionAbortedError)
        self.assertIsInstance(func(errno.ECONNREFUSED),
                ltpy.ConnectionRefusedError)
        self.assertIsInstance(func(errno.ECONNRESET),
                ltpy.ConnectionResetError)
        self.assertIsInstance(func(errno.EEXIST),
                ltpy.FileExistsError)
        self.assertIsInstance(func(errno.ENOENT),
                ltpy.FileNotFoundError)
        self.assertIsInstance(func(errno.EINTR),
                ltpy.InterruptedError)
        self.assertIsInstance(func(errno.EISDIR),
                ltpy.IsADirectoryError)
        self.assertIsInstance(func(errno.ENOTDIR),
                ltpy.NotADirectoryError)
        self.assertIsInstance(func(errno.EACCES),
                ltpy.PermissionError)
        self.assertIsInstance(func(errno.EPERM),
                ltpy.PermissionError)
        self.assertIsInstance(func(errno.ESRCH),
                ltpy.ProcessLookupError)
        self.assertIsInstance(func(errno.ETIMEDOUT),
                ltpy.TimeoutError)

    def test_upnp_category(self):
        def func(value):
            return ltpy.exception_from_error_code(lt.error_code(value,
                    lt.upnp_category()))

        self.assertIsInstance(func(1), ltpy.UPNPError)

    def test_http_category(self):
        def func(value):
            return ltpy.exception_from_error_code(lt.error_code(value,
                    lt.http_category()))

        self.assertIsInstance(func(1), ltpy.HTTPError)
        
    def test_socks_category(self):
        def func(value):
            return ltpy.exception_from_error_code(lt.error_code(value,
                    lt.socks_category()))

        self.assertIsInstance(func(1), ltpy.SOCKSError)

    def test_bdecode_category(self):
        def func(value):
            return ltpy.exception_from_error_code(lt.error_code(value,
                    lt.bdecode_category()))

        self.assertIsInstance(func(1), ltpy.BDecodeError)

    def test_i2p_category(self):
        def func(value):
            return ltpy.exception_from_error_code(lt.error_code(value,
                    lt.i2p_category()))

        self.assertIsInstance(func(1), ltpy.I2PError)

    def test_no_error(self):
        self.assertIsNone(ltpy.exception_from_error_code(lt.error_code(0,
            lt.libtorrent_category())))


class TestTranslateExceptions(unittest.TestCase):

    def test_real_enoent(self):
        with self.assertRaises(FileNotFoundError):
            with ltpy.translate_exceptions():
                lt.torrent_info("does-not-exist")

    def test_fake_runtimeerrors(self):
        with self.assertRaises(FileNotFoundError):
            with ltpy.translate_exceptions():
                raise RuntimeError(lt.generic_category().message(errno.ENOENT))

        with self.assertRaises(ltpy.DuplicateTorrentError):
            with ltpy.translate_exceptions():
                raise RuntimeError(lt.libtorrent_category().message(ltpy.LibtorrentErrorValue.DUPLICATE_TORRENT))
