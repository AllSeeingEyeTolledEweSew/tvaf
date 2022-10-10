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
from collections.abc import Hashable
from collections.abc import Iterator
import pathlib
import tempfile
from typing import Any
from typing import cast
import unittest

import anyio
import apsw
import dbver
import libtorrent as lt

from tvaf import concurrency
from tvaf import driver as driver_lib
from tvaf import ltpy
from tvaf import resume as resume_lib

from . import lib
from . import tdummy


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


class TerminateTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        session_service = lib.create_isolated_session_service()
        self.session = session_service.session
        self.torrent = tdummy.DEFAULT
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = pathlib.Path(self.tempdir.name)
        self.alert_driver = driver_lib.AlertDriver(
            session=self.session, use_alert_mask=session_service.use_alert_mask
        )
        self.resume = resume_lib.ResumeService(
            session=self.session,
            alert_driver=self.alert_driver,
            pool=dbver.null_pool(self.conn_factory),
        )
        self.resume.start()
        self.alert_driver_task = asyncio.create_task(self.alert_driver.run())

    async def asyncTearDown(self) -> None:
        self.resume.close()
        await asyncio.wait_for(self.resume.wait_closed(), 60)
        self.alert_driver.shutdown()
        with anyio.fail_after(60):
            await self.alert_driver_task
        await asyncio.to_thread(self.tempdir.cleanup)

    def conn_factory(self) -> apsw.Connection:
        return apsw.Connection(str(self.path / "resume.db"))

    async def get_resume_data(self) -> list[lt.add_torrent_params]:
        def inner() -> Iterator[lt.add_torrent_params]:
            with dbver.null_pool(self.conn_factory)() as conn:
                yield from resume_lib.iter_resume_data_from_db(conn)

        return await concurrency.alist(concurrency.iter_in_thread(inner()))

    async def test_mid_download(self) -> None:
        atp = self.torrent.atp()
        atp.flags &= ~lt.torrent_flags.paused
        atp.save_path = self.tempdir.name
        handle = self.session.add_torrent(atp)
        await asyncio.wait_for(lib.wait_done_checking_or_error(handle), 60)
        handle.add_piece(0, self.torrent.pieces[0], 0)

        for _ in lib.loop_until_timeout(60, msg="piece finish"):
            status = handle.status(flags=lt.torrent_handle.query_pieces)
            if any(status.pieces):
                break

        self.session.pause()
        self.resume.close()
        await asyncio.wait_for(self.resume.wait_closed(), 60)

        def atp_have_piece(atp: lt.add_torrent_params, index: int) -> bool:
            if atp.have_pieces[index]:
                return True
            ti = self.torrent.torrent_info()
            num_blocks = (ti.piece_size(index) - 1) // 16384 + 1
            bitmask = atp.unfinished_pieces.get(index, [])
            if len(bitmask) < num_blocks:
                return False
            return all(bitmask[i] for i in range(num_blocks))

        atps = await self.get_resume_data()
        self.assertEqual(len(atps), 1)
        atp = atps[0]
        self.assertTrue(atp_have_piece(atp, 0))

    async def test_finished(self) -> None:
        atp = self.torrent.atp()
        atp.flags &= ~lt.torrent_flags.paused
        atp.save_path = self.tempdir.name
        handle = self.session.add_torrent(atp)
        await asyncio.wait_for(lib.wait_done_checking_or_error(handle), 60)
        for i, piece in enumerate(self.torrent.pieces):
            handle.add_piece(i, piece, 0)

        for _ in lib.loop_until_timeout(60, msg="finished state"):
            status = handle.status()
            if status.state in (status.states.finished, status.states.seeding):
                break

        self.session.pause()
        self.resume.close()
        await asyncio.wait_for(self.resume.wait_closed(), 60)

        atps = await self.get_resume_data()
        self.assertEqual(len(atps), 1)
        atp = atps[0]
        self.assertNotEqual(len(atp.have_pieces), 0)
        self.assertTrue(all(atp.have_pieces))

    async def test_remove_before_save(self) -> None:
        for _ in lib.loop_until_timeout(60, msg="remove-before-save"):
            atp = self.torrent.atp()
            atp.flags &= ~lt.torrent_flags.paused
            atp.save_path = self.tempdir.name
            handle = self.session.add_torrent(atp)
            await asyncio.wait_for(lib.wait_done_checking_or_error(handle), 60)

            try:
                with ltpy.translate_exceptions():
                    self.session.remove_torrent(handle)
                    handle.save_resume_data()
                break
            except ltpy.InvalidTorrentHandleError:
                pass

        self.session.pause()
        self.resume.close()
        await asyncio.wait_for(self.resume.wait_closed(), 60)

        atps = await self.get_resume_data()
        self.assertEqual(atps, [])

    async def test_finish_remove_terminate(self) -> None:
        atp = self.torrent.atp()
        atp.flags &= ~lt.torrent_flags.paused
        atp.save_path = self.tempdir.name
        handle = self.session.add_torrent(atp)
        await asyncio.wait_for(lib.wait_done_checking_or_error(handle), 60)
        for i, piece in enumerate(self.torrent.pieces):
            handle.add_piece(i, piece, 0)

        for _ in lib.loop_until_timeout(60, msg="finished state"):
            status = handle.status()
            if status.state in (status.states.finished, status.states.seeding):
                break

        # Synchronously remove torrent and close
        self.session.remove_torrent(handle)
        self.session.pause()
        self.resume.close()
        await asyncio.wait_for(self.resume.wait_closed(), 60)

        atps = await self.get_resume_data()
        self.assertEqual(atps, [])


# TODO: test underflow, with and without pedantic

# TODO: test magnets

# TODO: test io errors, with and without pedantic

# TODO: test io errors when loading

# TODO: at end of tests, load atp into new session

# TODO: test save with invalid handle
