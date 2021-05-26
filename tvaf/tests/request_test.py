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

import concurrent.futures
import os
import os.path
import tempfile

import libtorrent as lt

from tvaf import ltpy

from . import lib
from . import request_test_utils


class TestAddRemove(request_test_utils.RequestServiceTestCase):
    def test_add_remove(self) -> None:
        req = self.add_req()
        self.wait_for_torrent()
        self.assertEqual(
            [h.info_hash() for h in self.session.get_torrents()],
            [self.torrent.sha1_hash],
        )
        self.service.discard_request(req)
        with self.assertRaises(ltpy.CanceledError):
            req.read(timeout=5)

    def test_shutdown(self) -> None:
        req = self.add_req()
        self.service.terminate()
        with self.assertRaises(ltpy.CanceledError):
            req.read(timeout=5)

    def test_already_shutdown(self) -> None:
        self.service.terminate()
        req = self.add_req()
        with self.assertRaises(ltpy.CanceledError):
            req.read(timeout=5)


class TestRead(request_test_utils.RequestServiceTestCase):
    def test_all(self) -> None:
        req = self.add_req()

        self.feed_pieces()

        data = request_test_utils.read_all(req)
        self.assertEqual(data, self.torrent.data)

    def test_unaligned_multi_pieces(self) -> None:
        start = self.torrent.piece_length // 2
        stop = min(start + self.torrent.piece_length, self.torrent.length)
        req = self.add_req(start=start, stop=stop)

        self.feed_pieces()

        data = request_test_utils.read_all(req)

        self.assertEqual(data, self.torrent.data[start:stop])

    def test_unaligned_single_piece(self) -> None:
        start = self.torrent.piece_length // 4
        stop = 3 * self.torrent.piece_length // 4
        req = self.add_req(start=start, stop=stop)

        self.feed_pieces()

        data = request_test_utils.read_all(req)

        self.assertEqual(data, self.torrent.data[start:stop])

    def test_existing_torrent(self) -> None:
        req = self.add_req()

        self.feed_pieces()

        request_test_utils.read_all(req)

        req = self.add_req()
        data = request_test_utils.read_all(req, msg="second read")

        self.assertEqual(data, self.torrent.data)

    def test_simultaneous(self) -> None:
        req1 = self.add_req()
        req2 = self.add_req()
        executor = concurrent.futures.ThreadPoolExecutor()
        future1 = executor.submit(request_test_utils.read_all, req1)
        future2 = executor.submit(request_test_utils.read_all, req2)

        self.feed_pieces()

        self.assertEqual(future1.result(), self.torrent.data)
        self.assertEqual(future2.result(), self.torrent.data)

    def test_two_readers(self) -> None:
        req1 = self.add_req()
        req2 = self.add_req()

        self.feed_pieces()

        data1 = request_test_utils.read_all(req1)
        data2 = request_test_utils.read_all(req2)

        self.assertEqual(data1, self.torrent.data)
        self.assertEqual(data2, self.torrent.data)

    def test_download(self) -> None:
        seed = lib.create_isolated_session_service().session
        seed_dir = tempfile.TemporaryDirectory()
        atp = self.torrent.atp()
        atp.save_path = seed_dir.name
        atp.flags &= ~lt.torrent_flags.paused
        handle = seed.add_torrent(atp)
        # https://github.com/arvidn/libtorrent/issues/4980: add_piece() while
        # checking silently fails in libtorrent 1.2.8.
        request_test_utils.wait_done_checking_or_error(handle)
        for i, piece in enumerate(self.torrent.pieces):
            # NB: bug in libtorrent where add_piece accepts str but not bytes
            handle.add_piece(i, piece.decode(), 0)

        req = self.add_req()
        self.wait_for_torrent().connect_peer(("127.0.0.1", seed.listen_port()))

        # The peer connection takes a long time, not sure why
        data = request_test_utils.read_all(req, timeout=60)
        self.assertEqual(data, self.torrent.data)

    def test_file_error(self) -> None:
        # Create a file in tempdir, try to use it as the save_path
        path = os.path.join(self.tempdir.name, "file.txt")
        with open(path, mode="w"):
            pass

        atp = self.torrent.atp()
        atp.save_path = path
        handle = self.session.add_torrent(atp)
        req = self.add_req(handle=handle)
        self.feed_pieces()

        with self.assertRaises(NotADirectoryError):
            request_test_utils.read_all(req)

    def test_read_checked_pieces(self) -> None:
        # Download a torrent
        req = self.add_req()
        self.feed_pieces()
        data = request_test_utils.read_all(req)
        self.assertEqual(data, self.torrent.data)

        # query_save_path not bound in python
        save_path = self.wait_for_torrent().status(flags=128).save_path

        # Wait for the file to be written to disk
        for _ in lib.loop_until_timeout(5, msg="write file"):
            path = os.path.join(save_path, self.torrent.files[0].path.decode())
            if os.path.exists(path):
                data = open(path, mode="rb").read()
                if data == self.torrent.data:
                    break

        # Create a new session
        self.teardown_session()
        self.init_session()
        req = self.add_req()

        # We should be able to read the data without feeding pieces
        data = request_test_utils.read_all(req)
        self.assertEqual(data, self.torrent.data)

    def test_read_after_cancelled_read(self) -> None:
        # Start reading
        req = self.add_req()
        # Feed one piece, so the torrent stays in the session
        self.feed_pieces(piece_indexes=(0,))

        # Wait for pieces to be prioritized
        for _ in lib.loop_until_timeout(5, msg="prioritize"):
            if all(self.wait_for_torrent().get_piece_priorities()):
                break

        # Cancel the request -- resets piece deadlines
        self.service.discard_request(req)

        # Wait until deadlines have been reset
        for _ in lib.loop_until_timeout(5, msg="deprioritize"):
            if not any(self.wait_for_torrent().get_piece_priorities()):
                break

        # Recreate the request -- listens for read_piece_alert
        req = self.add_req()
        # Feed all pieces and check that we can read the data
        self.feed_pieces()

        data = request_test_utils.read_all(req)
        self.assertEqual(data, self.torrent.data)


class TestRemoveTorrent(request_test_utils.RequestServiceTestCase):
    def test_with_active_requests(self) -> None:
        req = self.add_req()
        self.session.remove_torrent(self.wait_for_torrent())
        with self.assertRaises(ltpy.InvalidTorrentHandleError):
            req.read(timeout=5)
