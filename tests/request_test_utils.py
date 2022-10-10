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
import tempfile
import unittest

import anyio

from tvaf import driver as driver_lib
from tvaf import request as request_lib

from . import lib
from . import tdummy


class RequestServiceTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.torrent = tdummy.DEFAULT
        self.tempdir = await asyncio.to_thread(tempfile.TemporaryDirectory)

        session_service = lib.create_isolated_session_service()
        self.session = session_service.session
        self.alert_driver = driver_lib.AlertDriver(
            session=self.session, use_alert_mask=session_service.use_alert_mask
        )
        self.service = request_lib.RequestService(
            alert_driver=self.alert_driver,
            session=self.session,
        )

        self.alert_driver_task = asyncio.create_task(self.alert_driver.run())
        self.service.start()

        atp = self.torrent.atp()
        atp.save_path = self.tempdir.name
        self.handle = await asyncio.to_thread(
            self.session.add_torrent, atp  # type: ignore
        )
        self.all_pieces = range(len(self.torrent.pieces))

    async def asyncTearDown(self) -> None:
        self.service.close()
        await asyncio.wait_for(self.service.wait_closed(), 60)
        self.alert_driver.shutdown()
        with anyio.fail_after(60):
            await self.alert_driver_task
        await asyncio.to_thread(self.tempdir.cleanup)

    async def feed_pieces(self) -> None:
        piece_indexes = list(range(len(self.torrent.pieces)))
        # https://github.com/arvidn/libtorrent/issues/4980: add_piece() while
        # checking silently fails in libtorrent 1.2.8.
        await asyncio.wait_for(lib.wait_done_checking_or_error(self.handle), 60)
        if (await asyncio.to_thread(self.handle.status)).errc.value() != 0:
            return
        for i in piece_indexes:
            self.handle.add_piece(i, self.torrent.pieces[i], 0)
