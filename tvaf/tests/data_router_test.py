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
import os
import pathlib
import tempfile

import asgi_lifespan
import httpx
from later.unittest.backport import async_case

from tvaf import app as app_lib
from tvaf import concurrency
from tvaf import services

from . import lib
from . import tdummy


class AppTest(async_case.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tempdir = await concurrency.to_thread(tempfile.TemporaryDirectory)
        self.cwd = await concurrency.to_thread(pathlib.Path.cwd)
        await concurrency.to_thread(os.chdir, self.tempdir.name)
        self.config = lib.create_isolated_config()
        await self.config.write_to_disk(services.CONFIG_PATH)
        self.lifespan_manager = asgi_lifespan.LifespanManager(
            app_lib.APP, startup_timeout=None, shutdown_timeout=None
        )
        await self.lifespan_manager.__aenter__()
        self.client = httpx.AsyncClient(
            app=app_lib.APP, base_url="http://test"
        )

    async def asyncTearDown(self) -> None:
        await self.client.aclose()
        await self.lifespan_manager.__aexit__(None, None, None)
        await concurrency.to_thread(os.chdir, self.cwd)
        await concurrency.to_thread(self.tempdir.cleanup)


class FormatTest(AppTest, lib.TestCase):
    async def test_invalid_multihash(self) -> None:
        # not a valid multihash
        r = await self.client.get("/v1/btmh/ffff/i/0")
        self.assertEqual(r.status_code, 422)
        self.assert_golden_json(r.json(), suffix="invalid_multihash.json")

        # inconsistent sha1 length
        r = await self.client.get("/v1/btmh/1114a0/i/0")
        self.assertEqual(r.status_code, 422)
        self.assert_golden_json(r.json(), suffix="short_sha1.json")

        # wrong sha1 length (110100) -- should this be 422?

        # odd-numbered hex digits
        r = await self.client.get("/v1/btmh/a/i/0")
        self.assertEqual(r.status_code, 422)
        self.assert_golden_json(r.json(), suffix="odd_hex_digits.json")

        # not hexadecimal
        r = await self.client.get("/v1/btmh/not-hexadecimal/i/0")
        self.assertEqual(r.status_code, 422)
        self.assert_golden_json(r.json(), suffix="not_hexadecimal.json")

        # not sha1
        r = await self.client.get("/v1/btmh/1201cd/i/0")
        self.assertEqual(r.status_code, 404)
        self.assert_golden_json(r.json(), suffix="not_sha1.json")

    async def test_invalid_file_index(self) -> None:
        r = await self.client.get(
            "/v1/btmh/1114aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/i/-1"
        )
        self.assertEqual(r.status_code, 422)
        self.assert_golden_json(r.json(), suffix="negative_index.json")

        r = await self.client.get(
            "/v1/btmh/1114aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/i/a"
        )
        self.assertEqual(r.status_code, 422)
        self.assert_golden_json(r.json(), suffix="bad_index.json")


class AlreadyDownloadedTest(AppTest, lib.TestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.torrent = tdummy.DEFAULT_STABLE

        atp = self.torrent.atp()
        atp.save_path = self.tempdir.name
        session = await services.get_session()
        handle = await concurrency.to_thread(session.add_torrent, atp)
        # https://github.com/arvidn/libtorrent/issues/4980: add_piece() while
        # checking silently fails in libtorrent 1.2.8.
        await lib.wait_done_checking_or_error(handle)
        for i, piece in enumerate(self.torrent.pieces):
            handle.add_piece(i, piece, 0)

    async def test_head(self) -> None:
        r = await self.client.head(f"/v1/btmh/{self.torrent.btmh}/i/0")
        self.assertEqual(r.status_code, 200)
        self.assert_golden_json(dict(r.headers), suffix="headers.json")
        self.assertEqual(
            r.headers["content-length"], str(self.torrent.files[0].length)
        )

    async def test_get(self) -> None:
        r = await self.client.get(f"/v1/btmh/{self.torrent.btmh}/i/0")
        self.assertEqual(r.status_code, 200)
        self.assert_golden_json(dict(r.headers), suffix="headers.json")
        self.assertEqual(
            r.headers["content-length"], str(self.torrent.files[0].length)
        )
        self.assertEqual(r.content, self.torrent.files[0].data)

    async def test_206(self) -> None:
        r = await self.client.get(
            f"/v1/btmh/{self.torrent.btmh}/i/0",
            headers={"range": "bytes=100-199"},
        )
        self.assertEqual(r.status_code, 206)
        self.assert_golden_json(dict(r.headers), suffix="headers.json")
        self.assertEqual(r.headers["content-length"], "100")
        length = self.torrent.files[0].length
        self.assertEqual(r.headers["content-range"], f"bytes 100-199/{length}")
        self.assertEqual(r.content, self.torrent.files[0].data[100:200])

    async def test_206_if_range(self) -> None:
        r = await self.client.get(f"/v1/btmh/{self.torrent.btmh}/i/0")
        etag = r.headers["etag"]
        r = await self.client.get(
            f"/v1/btmh/{self.torrent.btmh}/i/0",
            headers={"range": "bytes=100-199", "if-range": etag},
        )
        self.assertEqual(r.status_code, 206)
        self.assertEqual(r.headers["content-length"], "100")
        length = self.torrent.files[0].length
        self.assertEqual(r.headers["content-range"], f"bytes 100-199/{length}")
        self.assertEqual(r.content, self.torrent.files[0].data[100:200])

    async def test_206_if_range_fail(self) -> None:
        r = await self.client.get(
            f"/v1/btmh/{self.torrent.btmh}/i/0",
            headers={"range": "bytes=100-199", "if-range": '"bad"'},
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(
            r.headers["content-length"], str(self.torrent.files[0].length)
        )
        self.assertEqual(r.content, self.torrent.files[0].data)

    async def test_416(self) -> None:
        r = await self.client.get(
            f"/v1/btmh/{self.torrent.btmh}/i/0",
            headers={"range": "bytes=999999999-"},
        )
        self.assertEqual(r.status_code, 416)
        self.assert_golden_json(dict(r.headers), suffix="headers.json")
        length = self.torrent.files[0].length
        self.assertEqual(r.headers["content-range"], f"bytes */{length}")

    async def test_304(self) -> None:
        r = await self.client.get(f"/v1/btmh/{self.torrent.btmh}/i/0")
        etag = r.headers["etag"]
        r = await self.client.get(
            f"/v1/btmh/{self.torrent.btmh}/i/0",
            headers={"if-none-match": etag},
        )
        self.assertEqual(r.status_code, 304)
        self.assert_golden_json(dict(r.headers), suffix="headers.json")


class SeedTest(AppTest):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.torrent = tdummy.DEFAULT_STABLE

        self.seed = lib.create_isolated_session_service().session
        self.seed_dir = await concurrency.to_thread(
            tempfile.TemporaryDirectory
        )
        atp = self.torrent.atp()
        atp.save_path = self.seed_dir.name
        handle = await concurrency.to_thread(self.seed.add_torrent, atp)
        # https://github.com/arvidn/libtorrent/issues/4980: add_piece() while
        # checking silently fails in libtorrent 1.2.8.
        await lib.wait_done_checking_or_error(handle)
        for i, piece in enumerate(self.torrent.pieces):
            handle.add_piece(i, piece, 0)
        self.seed_endpoint = ("127.0.0.1", self.seed.listen_port())
        self.seed_endpoint_str = f"127.0.0.1:{self.seed.listen_port()}"

    async def asyncTearDown(self) -> None:
        await super().asyncTearDown()
        await concurrency.to_thread(self.seed_dir.cleanup)


class PublicFallbackTest(SeedTest, lib.TestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.seed.apply_settings({"enable_dht": True})
        config = await services.get_config()
        config["session_dht_bootstrap_nodes"] = self.seed_endpoint_str
        config["session_enable_dht"] = True
        await services.set_config(config)

    async def test_head(self) -> None:
        r = await self.client.head(f"/v1/btmh/{self.torrent.btmh}/i/0")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(
            r.headers["content-length"], str(self.torrent.files[0].length)
        )
        self.assert_golden_json(dict(r.headers), suffix="headers.json")

    async def test_get(self) -> None:
        r = await self.client.get(f"/v1/btmh/{self.torrent.btmh}/i/0")
        self.assertEqual(r.status_code, 200)
        self.assert_golden_json(dict(r.headers), suffix="headers.json")
        self.assertEqual(
            r.headers["content-length"], str(self.torrent.files[0].length)
        )
        self.assertEqual(r.content, self.torrent.files[0].data)
