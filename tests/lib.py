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

"""Support code for other tests."""

from __future__ import annotations

from collections.abc import Iterator
import importlib
import importlib.metadata
import importlib.resources
import json
import os
import pathlib
import tempfile
import time
from typing import Any
import unittest
import unittest.mock

import anyio
import asgi_lifespan
import httpx
import libtorrent as lt

from tvaf import app as app_lib
from tvaf import concurrency
from tvaf import config as config_lib
from tvaf import services
from tvaf import session as session_lib

from . import tdummy


def create_isolated_config() -> config_lib.Config:
    return config_lib.Config(
        session_enable_dht=False,
        session_enable_lsd=False,
        session_enable_natpmp=False,
        session_enable_upnp=False,
        session_listen_interfaces="127.0.0.1:0",
        session_alert_mask=0,
        session_dht_bootstrap_nodes="",
    )


def create_isolated_session_service(
    *, alert_mask: int = 0
) -> session_lib.SessionService:
    return session_lib.SessionService(
        alert_mask=alert_mask, config=create_isolated_config()
    )


def loop_until_timeout(timeout: float, msg: str = "condition") -> Iterator[None]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        yield
    raise AssertionError(f"{msg} timed out")


async def wait_done_checking_or_error(handle: lt.torrent_handle) -> None:
    while True:
        status = await concurrency.to_thread(handle.status)
        if status.state not in (
            lt.torrent_status.states.checking_resume_data,
            lt.torrent_status.states.checking_files,
        ):
            break
        if status.errc.value() != 0:
            break


class TestCase(unittest.TestCase):
    """A base unittest.TestCase to provide some useful utilities."""

    maxDiff = None

    def get_meld_path(self, suffix: str) -> str:
        """Returns the path to write to update a golden data file."""
        # importlib.resources doesn't provide any way for updating files
        # that are assumed to be individually accessible on the filesystem. So
        # for updating golden data, we use the "naive" approach of referencing
        # a file based off of the __file__ path.
        return os.path.join(os.path.dirname(__file__), "data", f"{self.id()}.{suffix}")

    def get_data(self, suffix: str) -> str:
        """Returns golden reference data for this test."""
        files = importlib.resources.files("tests.data")
        resource = files / f"{self.id()}.{suffix}"
        return resource.read_text()

    def assert_golden(self, value: str, suffix: str = "golden.txt") -> None:
        """Asserts a value is equal to golden data, or update the golden data.

        Normally, this function reads a data file corresponding to the
        currently-running test, and compares the contents with the given value.
        If the values don't match, it raises AssertionError.

        If the GOLDEN_MELD environment variable is set to a nonempty string, it
        will update the golden data file with the contents instead, and no
        correctness test will be performed. This will only work if the tvaf
        project is laid out "normally" in the filesystem, i.e. not compressed
        in an egg.

        Args:
            value: The text value to test.
            suffix: A distinguishing suffix for the filename of the golden
                data.

        Raises:
            AssertionError: If the given value doesn't match the golden data,
                and GOLDEN_MELD is unset.
        """
        if os.environ.get("GOLDEN_MELD"):
            with open(self.get_meld_path(suffix), mode="w") as golden_fp:
                golden_fp.write(value)
        else:
            second = self.get_data(suffix)
            self.assertEqual(value, second)

    def assert_golden_json(
        self, value: Any, suffix: str = "golden.json", **kwargs: Any
    ):
        """Like assert_golden for the json text representation of a value.

        Args:
            value: Any value that will work with json.dump.
            suffix: A distinguishing suffix for the filename of the golden
                data.
            kwargs: Passed on to json.dump for comparison. This function
                overrides indent=4 in accordance with tvaf's formatting
                standards, and overrides sort_keys=True, which is essential for
                stable comparisons.

        Raises:
            AssertionError: If the given value doesn't match the golden data,
                and GOLDEN_MELD is unset.
        """
        kwargs["indent"] = 4
        kwargs["sort_keys"] = True
        value_text = json.dumps(value, **kwargs)
        self.assert_golden(value_text, suffix=suffix)


class AppTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.tempdir = await concurrency.to_thread(tempfile.TemporaryDirectory)
        self.cwd = await concurrency.to_thread(pathlib.Path.cwd)
        await concurrency.to_thread(os.chdir, self.tempdir.name)
        self.config = create_isolated_config()
        await self.config.write_to_disk(services.CONFIG_PATH)
        self.lifespan_manager = asgi_lifespan.LifespanManager(
            app_lib.APP, startup_timeout=None, shutdown_timeout=None
        )
        with anyio.fail_after(5):
            await self.lifespan_manager.__aenter__()

        # https://github.com/encode/httpx/issues/2239: httpx doesn't honor timeouts for
        # ASGI/WSGI

        async def app_with_timeout(*args) -> None:
            with anyio.fail_after(5):
                await app_lib.APP(*args)

        self.client = httpx.AsyncClient(
            app=app_with_timeout,
            base_url="http://test",
            follow_redirects=True,
            timeout=5,
        )

    async def asyncTearDown(self) -> None:
        with anyio.fail_after(5):
            await self.client.aclose()
            await self.lifespan_manager.__aexit__(None, None, None)
        await concurrency.to_thread(os.chdir, self.cwd)
        await concurrency.to_thread(self.tempdir.cleanup)


class AppTestWithTorrent(AppTest):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.torrent = tdummy.DEFAULT_STABLE

        atp = self.torrent.atp()
        atp.save_path = self.tempdir.name
        with anyio.fail_after(5):
            session = await services.get_session()
            self.handle = await concurrency.to_thread(session.add_torrent, atp)
            # https://github.com/arvidn/libtorrent/issues/4980: add_piece() while
            # checking silently fails in libtorrent 1.2.8.
            await wait_done_checking_or_error(self.handle)
        for i, piece in enumerate(self.torrent.pieces):
            self.handle.add_piece(i, piece, 0)
