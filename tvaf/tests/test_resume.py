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

import asyncio
import pathlib
import sys
import tempfile
from typing import Any
from typing import cast
from typing import Hashable
from typing import TypeVar
import unittest

import libtorrent as lt

from tvaf import concurrency
from tvaf import driver as driver_lib
from tvaf import ltpy
from tvaf import resume as resume_lib

from . import lib
from . import tdummy


def setUpModule() -> None:
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def normalize(bdecoded: dict[bytes, Any]) -> dict[bytes, Any]:
    # This normalizes any preformatted components
    return cast(dict[bytes, Any], lt.bdecode(lt.bencode(bdecoded)))


def hashable(obj: Any) -> Hashable:
    if isinstance(obj, (list, tuple)):
        return tuple(hashable(x) for x in obj)
    if isinstance(obj, dict):
        return tuple(sorted((k, hashable(v)) for k, v in obj.items()))
    return cast(Hashable, obj)


def atp_hashable(atp: lt.add_torrent_params) -> Hashable:
    return hashable(normalize(lt.write_resume_data(atp)))


def atp_comparable(atp: lt.add_torrent_params) -> dict[bytes, Any]:
    return normalize(lt.write_resume_data(atp))


_T = TypeVar("_T")


class IterResumeDataTest(unittest.IsolatedAsyncioTestCase):

    maxDiff = None

    TORRENT1 = tdummy.Torrent.single_file(name=b"1.txt", length=1024)
    TORRENT2 = tdummy.Torrent.single_file(name=b"2.txt", length=1024)
    TORRENT3 = tdummy.Torrent.single_file(name=b"3.txt", length=1024)

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = pathlib.Path(self.tempdir.name)

        def write(torrent: tdummy.Torrent) -> None:
            self.path.mkdir(parents=True, exist_ok=True)
            path = self.path.joinpath(str(torrent.sha1_hash)).with_suffix(".resume")
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
        got: list[lt.add_torrent_params],
        expected: list[lt.add_torrent_params],
    ) -> None:
        self.assertEqual(
            [atp_comparable(atp) for atp in got],
            [atp_comparable(atp) for atp in expected],
        )

    def assert_atp_sets_equal(
        self,
        got: set[lt.add_torrent_params],
        expected: set[lt.add_torrent_params],
    ) -> None:
        self.assertEqual(
            {atp_hashable(atp) for atp in got},
            {atp_hashable(atp) for atp in expected},
        )

    async def asyncTearDown(self) -> None:
        await concurrency.to_thread(
            lib.cleanup_with_windows_fix, self.tempdir, timeout=5
        )

    async def test_normal(self) -> None:
        atps = await concurrency.alist(resume_lib.iter_resume_data_from_disk(self.path))
        self.assert_atp_sets_equal(
            set(atps), {self.TORRENT1.atp(), self.TORRENT2.atp()}
        )

    async def test_ignore_bad_data(self) -> None:
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

        atps = await concurrency.alist(resume_lib.iter_resume_data_from_disk(self.path))
        self.assert_atp_sets_equal(
            set(atps), {self.TORRENT1.atp(), self.TORRENT2.atp()}
        )


class TerminateTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.session_service = lib.create_isolated_session_service()
        self.session = self.session_service.session
        self.torrent = tdummy.DEFAULT
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = pathlib.Path(self.tempdir.name)
        self.alert_driver = driver_lib.AlertDriver(session_service=self.session_service)
        self.resume = resume_lib.ResumeService(
            session=self.session,
            alert_driver=self.alert_driver,
            path=self.path,
        )
        self.resume.start()
        self.alert_driver.start()

    async def asyncTearDown(self) -> None:
        self.resume.close()
        await asyncio.wait_for(self.resume.wait_closed(), 5)
        self.alert_driver.close()
        await asyncio.wait_for(self.alert_driver.wait_closed(), 5)
        await concurrency.to_thread(
            lib.cleanup_with_windows_fix, self.tempdir, timeout=5
        )

    async def test_mid_download(self) -> None:
        atp = self.torrent.atp()
        atp.flags &= ~lt.torrent_flags.paused
        atp.save_path = self.tempdir.name
        handle = self.session.add_torrent(atp)
        await asyncio.wait_for(lib.wait_done_checking_or_error(handle), 5)
        handle.add_piece(0, self.torrent.pieces[0], 0)

        for _ in lib.loop_until_timeout(5, msg="piece finish"):
            status = handle.status(flags=lt.torrent_handle.query_pieces)
            if any(status.pieces):
                break

        self.session.pause()
        self.resume.close()
        await asyncio.wait_for(self.resume.wait_closed(), 5)

        def atp_have_piece(atp: lt.add_torrent_params, index: int) -> bool:
            if atp.have_pieces[index]:
                return True
            ti = self.torrent.torrent_info()
            num_blocks = (ti.piece_size(index) - 1) // 16384 + 1
            bitmask = atp.unfinished_pieces.get(index, [])
            if len(bitmask) < num_blocks:
                return False
            return all(bitmask[i] for i in range(num_blocks))

        atps = await concurrency.alist(resume_lib.iter_resume_data_from_disk(self.path))
        self.assertEqual(len(atps), 1)
        atp = atps[0]
        self.assertTrue(atp_have_piece(atp, 0))

    async def test_finished(self) -> None:
        atp = self.torrent.atp()
        atp.flags &= ~lt.torrent_flags.paused
        atp.save_path = self.tempdir.name
        handle = self.session.add_torrent(atp)
        await asyncio.wait_for(lib.wait_done_checking_or_error(handle), 5)
        for i, piece in enumerate(self.torrent.pieces):
            handle.add_piece(i, piece, 0)

        for _ in lib.loop_until_timeout(5, msg="finished state"):
            status = handle.status()
            if status.state in (status.states.finished, status.states.seeding):
                break

        self.session.pause()
        self.resume.close()
        await asyncio.wait_for(self.resume.wait_closed(), 5)

        atps = await concurrency.alist(resume_lib.iter_resume_data_from_disk(self.path))
        self.assertEqual(len(atps), 1)
        atp = atps[0]
        self.assertNotEqual(len(atp.have_pieces), 0)
        self.assertTrue(all(atp.have_pieces))

    async def test_remove_before_save(self) -> None:
        for _ in lib.loop_until_timeout(5, msg="remove-before-save"):
            atp = self.torrent.atp()
            atp.flags &= ~lt.torrent_flags.paused
            atp.save_path = self.tempdir.name
            handle = self.session.add_torrent(atp)
            await asyncio.wait_for(lib.wait_done_checking_or_error(handle), 5)

            try:
                with ltpy.translate_exceptions():
                    self.session.remove_torrent(handle)
                    handle.save_resume_data()
                break
            except ltpy.InvalidTorrentHandleError:
                pass

        self.session.pause()
        self.resume.close()
        await asyncio.wait_for(self.resume.wait_closed(), 5)

        atps = await concurrency.alist(resume_lib.iter_resume_data_from_disk(self.path))
        self.assertEqual(atps, [])

    async def test_finish_remove_terminate(self) -> None:
        atp = self.torrent.atp()
        atp.flags &= ~lt.torrent_flags.paused
        atp.save_path = self.tempdir.name
        handle = self.session.add_torrent(atp)
        await asyncio.wait_for(lib.wait_done_checking_or_error(handle), 5)
        for i, piece in enumerate(self.torrent.pieces):
            handle.add_piece(i, piece, 0)

        for _ in lib.loop_until_timeout(5, msg="finished state"):
            status = handle.status()
            if status.state in (status.states.finished, status.states.seeding):
                break

        # Synchronously remove torrent and close
        self.session.remove_torrent(handle)
        self.session.pause()
        self.resume.close()
        await asyncio.wait_for(self.resume.wait_closed(), 5)

        atps = await concurrency.alist(resume_lib.iter_resume_data_from_disk(self.path))
        self.assertEqual(atps, [])


# TODO: test underflow, with and without pedantic

# TODO: test magnets

# TODO: test io errors, with and without pedantic

# TODO: test io errors when loading

# TODO: at end of tests, load atp into new session

# TODO: test save with invalid handle
