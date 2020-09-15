import pathlib
import tempfile
import unittest

import libtorrent as lt

from tvaf import config as config_lib
from tvaf import driver as driver_lib
from tvaf import lt4604
from tvaf import request as request_lib
from tvaf import resume as resume_lib

from . import lib
from . import tdummy


def wait_done_checking_or_error(handle: lt.torrent_handle):
    for _ in lib.loop_until_timeout(5, msg="checking (or error)"):
        status = handle.status()
        if status.state not in (lt.torrent_status.states.checking_resume_data,
                                lt.torrent_status.states.checking_files):
            break
        if status.errc.value() != 0:
            break


def read_all(request: request_lib.Request, msg="read all data", timeout=5):
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

    def setUp(self):
        self.torrent = tdummy.DEFAULT
        self.tempdir = tempfile.TemporaryDirectory()
        self.config_dir = pathlib.Path(self.tempdir.name)
        self.config = config_lib.Config()
        self.init_session()

    def teardown_session(self):
        self.service.terminate()
        self.service.join()
        self.resume_service.terminate()
        self.resume_service.join()
        self.alert_driver.terminate()
        self.alert_driver.join()

    def init_session(self):
        self.session_service = lib.create_isolated_session_service()
        self.session = self.session_service.session
        self.alert_driver = driver_lib.AlertDriver(
            session_service=self.session_service)
        self.resume_service = resume_lib.ResumeService(
            config_dir=self.config_dir,
            alert_driver=self.alert_driver,
            session=self.session)
        self.service = request_lib.RequestService(
            session=self.session,
            config=self.config,
            config_dir=self.config_dir,
            alert_driver=self.alert_driver,
            resume_service=self.resume_service)
        self.lt4604_fixup = lt4604.Fixup(alert_driver=self.alert_driver)

        self.alert_driver.start()
        # Not currently starting ResumeService
        self.service.start()
        self.resume_service.start()

    def tearDown(self):
        self.teardown_session()
        self.tempdir.cleanup()

    def feed_pieces(self, piece_indexes=None):
        if not piece_indexes:
            piece_indexes = list(range(len(self.torrent.pieces)))
        handle = self.wait_for_torrent()
        # https://github.com/arvidn/libtorrent/issues/4980: add_piece() while
        # checking silently fails in libtorrent 1.2.8.
        wait_done_checking_or_error(handle)
        for i in piece_indexes:
            # NB: bug in libtorrent where add_piece accepts str but not bytes
            handle.add_piece(i, self.torrent.pieces[i].decode(), 0)

    def add_req(self,
                mode=request_lib.Mode.READ,
                start=None,
                stop=None,
                get_add_torrent_params=None):
        if start is None:
            start = 0
        if stop is None:
            stop = self.torrent.length
        if get_add_torrent_params is None:
            get_add_torrent_params = self.torrent.atp
        return self.service.add_request(
            mode=mode,
            info_hash=self.torrent.infohash,
            start=start,
            stop=stop,
            get_add_torrent_params=get_add_torrent_params)

    def wait_for_torrent(self):
        handle = None
        for _ in lib.loop_until_timeout(5, msg="add torrent"):
            handle = self.session.find_torrent(
                lt.sha1_hash(bytes.fromhex(self.torrent.infohash)))
            if handle.is_valid():
                break
        return handle
