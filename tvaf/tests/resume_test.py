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

import pathlib
import tempfile
from typing import Any
from typing import cast
from typing import Dict
from typing import Hashable
from typing import List
from typing import Set
import unittest

import libtorrent as lt

from tvaf import driver as driver_lib
from tvaf import ltpy
from tvaf import resume as resume_lib

from . import lib
from . import request_test_utils
from . import tdummy


def atp_dict_fixup(atp_dict: Dict[bytes, Any]) -> Dict[bytes, Any]:
    return cast(Dict[bytes, Any], lt.bdecode(lt.bencode(atp_dict)))


def hashable(obj: Any) -> Hashable:
    if isinstance(obj, (list, tuple)):
        return tuple(hashable(x) for x in obj)
    if isinstance(obj, dict):
        return tuple(sorted((k, hashable(v)) for k, v in obj.items()))
    return cast(Hashable, obj)


def atp_hashable(atp: lt.add_torrent_params) -> Hashable:
    return hashable(atp_dict_fixup(lt.write_resume_data(atp)))


def atp_comparable(atp: lt.add_torrent_params) -> Dict[bytes, Any]:
    return atp_dict_fixup(lt.write_resume_data(atp))


class IterResumeDataTest(unittest.TestCase):

    maxDiff = None

    TORRENT1 = tdummy.Torrent.single_file(name=b"1.txt", length=1024)
    TORRENT2 = tdummy.Torrent.single_file(name=b"2.txt", length=1024)
    TORRENT3 = tdummy.Torrent.single_file(name=b"3.txt", length=1024)

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = pathlib.Path(self.tempdir.name)

        def write(torrent: tdummy.Torrent) -> None:
            self.path.mkdir(parents=True, exist_ok=True)
            path = self.path.joinpath(torrent.info_hash).with_suffix(".resume")
            atp = torrent.atp()
            atp.ti = None
            atp_data = lt.bencode(lt.write_resume_data(atp))
            path.write_bytes(atp_data)
            ti_data = lt.bencode(torrent.dict)
            path.with_suffix(".torrent").write_bytes(ti_data)

        write(self.TORRENT1)
        write(self.TORRENT2)

    def assert_atp_equal(
        self, got: lt.add_torrent_params, expected: lt.add_torrent_params
    ) -> None:
        self.assertEqual(atp_comparable(got), atp_comparable(expected))

    def assert_atp_list_equal(
        self,
        got: List[lt.add_torrent_params],
        expected: List[lt.add_torrent_params],
    ) -> None:
        self.assertEqual(
            [atp_comparable(atp) for atp in got],
            [atp_comparable(atp) for atp in expected],
        )

    def assert_atp_sets_equal(
        self,
        got: Set[lt.add_torrent_params],
        expected: Set[lt.add_torrent_params],
    ) -> None:
        self.assertEqual(
            {atp_hashable(atp) for atp in got},
            {atp_hashable(atp) for atp in expected},
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_normal(self) -> None:
        atps = list(resume_lib.iter_resume_data_from_disk(self.path))
        self.assert_atp_sets_equal(
            set(atps), {self.TORRENT1.atp(), self.TORRENT2.atp()}
        )

    def test_ignore_bad_data(self) -> None:
        # valid resume data, wrong filename
        path = self.path.joinpath("00" * 20).with_suffix(".tmp")
        data = lt.bencode(lt.write_resume_data(self.TORRENT3.atp()))
        path.write_bytes(data)

        # valid resume data, wrong filename
        path = self.path.joinpath("whoopsie").with_suffix(".resume")
        data = lt.bencode(lt.write_resume_data(self.TORRENT3.atp()))
        path.write_bytes(data)

        # good file name, non-bencoded data
        path = self.path.joinpath("00" * 20).with_suffix(".resume")
        path.write_text("whoopsie")

        # good file name, bencoded data, but not a resume file
        path = self.path.joinpath("01" * 20).with_suffix(".resume")
        path.write_bytes(lt.bencode(self.TORRENT1.info))

        # good file name, inaccessible
        path = self.path.joinpath("02" * 20).with_suffix(".resume")
        path.symlink_to("does_not_exist.resume")

        atps = list(resume_lib.iter_resume_data_from_disk(self.path))
        self.assert_atp_sets_equal(
            set(atps), {self.TORRENT1.atp(), self.TORRENT2.atp()}
        )


class TerminateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.session_service = lib.create_isolated_session_service()
        self.session = self.session_service.session
        self.torrent = tdummy.DEFAULT
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = pathlib.Path(self.tempdir.name)
        self.alert_driver = driver_lib.AlertDriver(
            session_service=self.session_service
        )
        self.resume = resume_lib.ResumeService(
            session=self.session,
            alert_driver=self.alert_driver,
            pedantic=True,
            path=self.path,
        )
        self.resume.start()
        self.alert_driver.start()

    def tearDown(self) -> None:
        self.resume.terminate()
        self.resume.join()
        self.alert_driver.terminate()
        self.alert_driver.join()
        self.tempdir.cleanup()

    def test_mid_download(self) -> None:
        atp = self.torrent.atp()
        atp.flags &= ~lt.torrent_flags.paused
        atp.save_path = self.tempdir.name
        handle = self.session.add_torrent(atp)
        request_test_utils.wait_done_checking_or_error(handle)
        # NB: bug in libtorrent where add_piece accepts str but not bytes
        handle.add_piece(0, self.torrent.pieces[0].decode(), 0)

        for _ in lib.loop_until_timeout(5, msg="piece finish"):
            status = handle.status(flags=lt.torrent_handle.query_pieces)
            if any(status.pieces):
                break

        self.session.pause()
        self.resume.terminate()
        self.resume.join()

        def atp_have_piece(atp: lt.add_torrent_params, index: int) -> bool:
            if atp.have_pieces[index]:
                return True
            ti = self.torrent.torrent_info()
            num_blocks = (ti.piece_size(index) - 1) // 16384 + 1
            bitmask = atp.unfinished_pieces.get(index, [])
            if len(bitmask) < num_blocks:
                return False
            return all(bitmask[i] for i in range(num_blocks))

        atps = list(resume_lib.iter_resume_data_from_disk(self.path))
        self.assertEqual(len(atps), 1)
        atp = atps[0]
        self.assertTrue(atp_have_piece(atp, 0))

    def test_finished(self) -> None:
        atp = self.torrent.atp()
        atp.flags &= ~lt.torrent_flags.paused
        atp.save_path = self.tempdir.name
        handle = self.session.add_torrent(atp)
        request_test_utils.wait_done_checking_or_error(handle)
        for i, piece in enumerate(self.torrent.pieces):
            # NB: bug in libtorrent where add_piece accepts str but not bytes
            handle.add_piece(i, piece.decode(), 0)

        for _ in lib.loop_until_timeout(5, msg="finished state"):
            status = handle.status()
            if status.state in (status.states.finished, status.states.seeding):
                break

        self.session.pause()
        self.resume.terminate()
        self.resume.join()

        atps = list(resume_lib.iter_resume_data_from_disk(self.path))
        self.assertEqual(len(atps), 1)
        atp = atps[0]
        self.assertNotEqual(len(atp.have_pieces), 0)
        self.assertTrue(all(atp.have_pieces))

    def test_remove_before_save(self) -> None:
        for _ in lib.loop_until_timeout(5, msg="remove-before-save"):
            atp = self.torrent.atp()
            atp.flags &= ~lt.torrent_flags.paused
            atp.save_path = self.tempdir.name
            handle = self.session.add_torrent(atp)
            request_test_utils.wait_done_checking_or_error(handle)

            try:
                with ltpy.translate_exceptions():
                    self.session.remove_torrent(handle)
                    self.resume.save(handle)
                break
            except ltpy.InvalidTorrentHandleError:
                pass

        self.session.pause()
        self.resume.terminate()
        self.resume.join()

        atps = list(resume_lib.iter_resume_data_from_disk(self.path))
        self.assertEqual(atps, [])

    def test_finish_remove_terminate(self) -> None:
        atp = self.torrent.atp()
        atp.flags &= ~lt.torrent_flags.paused
        atp.save_path = self.tempdir.name
        handle = self.session.add_torrent(atp)
        request_test_utils.wait_done_checking_or_error(handle)
        for i, piece in enumerate(self.torrent.pieces):
            # NB: bug in libtorrent where add_piece accepts str but not bytes
            handle.add_piece(i, piece.decode(), 0)

        for _ in lib.loop_until_timeout(5, msg="finished state"):
            status = handle.status()
            if status.state in (status.states.finished, status.states.seeding):
                break

        # Remove, pause and terminate before we process any alerts.
        # ResumeService should try to save_resume_data() on an invalid handle.
        # This is timing-dependent but I don't have a way to force it.
        self.session.remove_torrent(handle)
        self.session.pause()
        self.resume.terminate()
        self.resume.join()

        atps = list(resume_lib.iter_resume_data_from_disk(self.path))
        self.assertEqual(atps, [])


# TODO: test underflow, with and without pedantic

# TODO: test magnets

# TODO: test io errors, with and without pedantic

# TODO: test io errors when loading

# TODO: at end of tests, load atp into new session

# TODO: test save with invalid handle
