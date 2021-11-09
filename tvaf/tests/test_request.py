# Copyright (c) 2021 AllSeeingEyeTolledEweSew
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

import asyncio
import os
import pathlib
import tempfile
from typing import List
from typing import Sequence

import libtorrent as lt

from tvaf import concurrency
from tvaf import ltpy

from . import lib
from . import request_test_utils


class TestReadPiecesWithCancellation(request_test_utils.RequestServiceTestCase):
    async def test_remove_before_start(self) -> None:
        self.session.remove_torrent(self.handle)
        # Ensure removal happened before we do read_pieces()
        while await concurrency.to_thread(self.session.get_torrents):
            pass
        it = self.service.read_pieces(self.handle, self.all_pieces)
        with self.assertRaises(ltpy.InvalidTorrentHandleError):
            await asyncio.wait_for(it.__anext__(), 5)

    async def test_remove_after_start(self) -> None:
        # Schedule removal after we start read_pieces()
        async def do_remove() -> None:
            self.session.remove_torrent(self.handle)

        asyncio.create_task(do_remove())
        it = self.service.read_pieces(self.handle, self.all_pieces)
        with self.assertRaises(ltpy.InvalidTorrentHandleError):
            await asyncio.wait_for(it.__anext__(), 5)

    async def test_shutdown(self) -> None:
        async def do_close() -> None:
            self.service.close()

        asyncio.create_task(do_close())
        it = self.service.read_pieces(self.handle, self.all_pieces)
        with self.assertRaises(asyncio.CancelledError):
            await asyncio.wait_for(it.__anext__(), 5)

    async def test_file_error(self) -> None:
        self.session.remove_torrent(self.handle)
        # Create a file in tempdir, try to use it as the save_path
        path = pathlib.Path(self.tempdir.name) / "file.txt"
        await concurrency.to_thread(path.write_bytes, b"")
        atp = self.torrent.atp()
        atp.save_path = str(path)
        self.handle = await concurrency.to_thread(self.session.add_torrent, atp)
        await self.feed_pieces()

        it = self.service.read_pieces(self.handle, self.all_pieces)
        with self.assertRaises(NotADirectoryError):
            await asyncio.wait_for(it.__anext__(), 5)

    # TODO: test de-prioritization


class TestReadPieces(request_test_utils.RequestServiceTestCase):
    async def read(self, pieces: Sequence[int]) -> List[bytes]:
        result: List[bytes] = []
        it = self.service.read_pieces(self.handle, pieces)
        async for piece in it:
            result.append(piece)
        return result

    async def test_read_all(self) -> None:
        await self.feed_pieces()
        pieces = await asyncio.wait_for(self.read(self.all_pieces), 5)
        self.assertEqual(pieces, self.torrent.pieces)

    async def test_out_of_order(self) -> None:
        await self.feed_pieces()
        pieces = await asyncio.wait_for(self.read([1, 0]), 5)
        self.assertEqual(pieces, [self.torrent.pieces[1], self.torrent.pieces[0]])

    async def test_duplicates(self) -> None:
        await self.feed_pieces()
        pieces = await asyncio.wait_for(self.read([0, 0]), 5)
        self.assertEqual(pieces, [self.torrent.pieces[0], self.torrent.pieces[0]])

    async def test_repetition(self) -> None:
        await self.feed_pieces()
        for _ in range(5):
            pieces = await asyncio.wait_for(self.read(self.all_pieces), 5)
            self.assertEqual(pieces, self.torrent.pieces)

    async def test_concurrent(self) -> None:
        task1 = asyncio.create_task(self.read(self.all_pieces))
        task2 = asyncio.create_task(self.read(self.all_pieces))
        await self.feed_pieces()
        pieces_list = await asyncio.wait_for(asyncio.gather(task1, task2), 5)
        for pieces in pieces_list:
            self.assertEqual(pieces, self.torrent.pieces)

    async def test_download(self) -> None:
        seed = lib.create_isolated_session_service().session
        seed_dir = await concurrency.to_thread(tempfile.TemporaryDirectory)
        try:
            atp = self.torrent.atp()
            atp.save_path = seed_dir.name
            atp.flags &= ~lt.torrent_flags.paused
            seed_handle = await concurrency.to_thread(seed.add_torrent, atp)
            # https://github.com/arvidn/libtorrent/issues/4980: add_piece()
            # while checking silently fails in libtorrent 1.2.8.
            await lib.wait_done_checking_or_error(seed_handle)
            for i, piece in enumerate(self.torrent.pieces):
                seed_handle.add_piece(i, piece, 0)

            self.handle.connect_peer(("127.0.0.1", seed.listen_port()))

            # The peer connection takes a long time, not sure why
            pieces = await asyncio.wait_for(self.read(self.all_pieces), 60)
        finally:
            await concurrency.to_thread(seed_dir.cleanup)
        self.assertEqual(pieces, self.torrent.pieces)

    async def test_read_checked_pieces(self) -> None:
        # write data to disk
        path = pathlib.Path(self.tempdir.name) / os.fsdecode(self.torrent.files[0].path)
        await concurrency.to_thread(path.write_bytes, self.torrent.files[0].data)
        # recheck the torrent
        self.handle.force_recheck()

        pieces = await asyncio.wait_for(self.read(self.all_pieces), 5)
        self.assertEqual(pieces, self.torrent.pieces)

    async def test_read_after_cancelled_read(self) -> None:
        await self.feed_pieces()
        it = self.service.read_pieces(self.handle, self.all_pieces)
        async for _ in it:
            break
        pieces = await asyncio.wait_for(self.read(self.all_pieces), 5)
        self.assertEqual(pieces, self.torrent.pieces)
