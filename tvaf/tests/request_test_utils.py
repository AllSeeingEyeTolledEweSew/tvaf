# Copyright (c) 2020 AllSeeingEyeTolledEweSew
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

import os
import tempfile
import unittest

import libtorrent as lt

from tvaf import config as config_lib
from tvaf import driver as driver_lib
from tvaf import request as request_lib
from tvaf import resume as resume_lib

from . import lib
from . import tdummy


def wait_done_checking_or_error(handle: lt.torrent_handle) -> None:
    for _ in lib.loop_until_timeout(5, msg="checking (or error)"):
        status = handle.status()
        if status.state not in (
            lt.torrent_status.states.checking_resume_data,
            lt.torrent_status.states.checking_files,
        ):
            break
        if status.errc.value() != 0:
            break


def read_all(
    request: request_lib.Request,
    msg: str = "read all data",
    timeout: float = 5,
) -> bytes:
    chunks = []
    for _ in lib.loop_until_timeout(timeout, msg=msg):
        chunk = request.read(timeout=0)
        if chunk is not None:
            if len(chunk) == 0:
                break
            chunks.append(bytes(chunk))
    return b"".join(chunks)


class RequestServiceTestCase(unittest.TestCase):
    """Tests for tvaf.dal.create_schema()."""

    def setUp(self) -> None:
        self.torrent = tdummy.DEFAULT
        self.tempdir = tempfile.TemporaryDirectory()
        self.cwd = os.getcwd()
        os.chdir(self.tempdir.name)
        self.config = config_lib.Config()
        self.init_session()

    def teardown_session(self) -> None:
        self.service.terminate()
        self.service.join()
        self.resume_service.terminate()
        self.resume_service.join()
        self.alert_driver.terminate()
        self.alert_driver.join()

    def init_session(self) -> None:
        self.session_service = lib.create_isolated_session_service()
        self.session = self.session_service.session
        self.alert_driver = driver_lib.AlertDriver(
            session_service=self.session_service
        )
        self.resume_service = resume_lib.ResumeService(
            alert_driver=self.alert_driver,
            session=self.session,
            path=self.tempdir.name,
        )
        self.service = request_lib.RequestService(
            session=self.session,
            config=self.config,
            alert_driver=self.alert_driver,
            resume_service=self.resume_service,
        )

        self.alert_driver.start()
        self.service.start()
        self.resume_service.start()

    def tearDown(self) -> None:
        self.teardown_session()
        os.chdir(self.cwd)
        self.tempdir.cleanup()

    def feed_pieces(self, piece_indexes=None) -> None:
        if not piece_indexes:
            piece_indexes = list(range(len(self.torrent.pieces)))
        handle = self.wait_for_torrent()
        # https://github.com/arvidn/libtorrent/issues/4980: add_piece() while
        # checking silently fails in libtorrent 1.2.8.
        wait_done_checking_or_error(handle)
        if handle.status().errc.value() != 0:
            return
        for i in piece_indexes:
            # NB: bug in libtorrent where add_piece accepts str but not bytes
            handle.add_piece(i, self.torrent.pieces[i].decode(), 0)

    def add_req(
        self,
        mode=request_lib.Mode.READ,
        start=None,
        stop=None,
        configure_atp=None,
    ) -> request_lib.Request:
        if start is None:
            start = 0
        if stop is None:
            stop = self.torrent.length
        if configure_atp is None:
            configure_atp = self.torrent.configure_atp
        return self.service.add_request(
            mode=mode,
            info_hash=self.torrent.info_hash,
            start=start,
            stop=stop,
            configure_atp=configure_atp,
        )

    def wait_for_torrent(self) -> lt.torrent_handle:
        for _ in lib.loop_until_timeout(5, msg="add torrent"):
            handle = self.session.find_torrent(
                lt.sha1_hash(bytes.fromhex(self.torrent.info_hash))
            )
            if handle.is_valid():
                return handle
        raise AssertionError("unreachable")
