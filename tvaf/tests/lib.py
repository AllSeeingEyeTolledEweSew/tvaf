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

"""Support code for other tests."""

# mypy currently chokes on importlib.resources; typeshed shadows the backported
# module no matter what I do


import collections
import email.message
import importlib
import io
import json
import os
import pathlib
import sys
import tempfile
import time
from typing import Any
from typing import cast
from typing import Dict
from typing import Iterable
from typing import Iterator
from typing import List
from typing import Optional
from typing import Tuple
from typing import Union
import unittest
import unittest.mock
import uuid

import asgi_lifespan
import httpx
import importlib_resources
from later.unittest.backport import async_case
import libtorrent as lt

from tvaf import app as app_lib
from tvaf import concurrency
from tvaf import config as config_lib
from tvaf import services
from tvaf import session as session_lib

from . import tdummy

if sys.version_info >= (3, 8):
    import importlib.metadata as importlib_metadata
else:
    import importlib_metadata


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


def loop_until_timeout(
    timeout: float, msg: str = "condition"
) -> Iterator[None]:
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
        # importlib_resources doesn't provide any way for updating files
        # that are assumed to be individually accessible on the filesystem. So
        # for updating golden data, we use the "naive" approach of referencing
        # a file based off of the __file__ path.
        return os.path.join(
            os.path.dirname(__file__), "data", f"{self.id()}.{suffix}"
        )

    def get_data(self, suffix: str) -> str:
        """Returns golden reference data for this test."""
        files = importlib_resources.files("tvaf.tests.data")
        resource = files / f"{self.id()}.{suffix}"
        return cast(str, resource.read_text())

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


class _FakeDistribution(importlib_metadata.Distribution):
    def __init__(self) -> None:
        self._entry_points: Dict[
            str, List[Tuple[str, str]]
        ] = collections.defaultdict(list)
        # Some amount of metadata is expected. In particular,
        # importlib_metadata de-duplicates distributions by name, for some
        # cases
        self._meta = email.message.Message()
        self._meta["Name"] = uuid.uuid4().hex
        self._meta["Metadata-Version"] = "2.1"
        self._meta["Version"] = "1.0"

    def add_entry_point(self, group: str, name: str, value: str) -> None:
        self._entry_points[group].append((name, value))

    def locate_file(self, path: Union[str, os.PathLike]) -> os.PathLike:
        return pathlib.Path("__DOES_NOT_EXIST__").joinpath(path)

    def read_text(self, filename: str) -> Optional[str]:
        if filename == "entry_points.txt":
            fp = io.StringIO()
            for group, name_values in self._entry_points.items():
                fp.write("[")
                fp.write(group)
                fp.write("]\n")
                for name, value in name_values:
                    fp.write(name)
                    fp.write(" = ")
                    fp.write(value)
                    fp.write("\n")
                fp.write("\n")
            return fp.getvalue()
        if filename == "PKG-INFO":
            return self._meta.as_string()
        return None


_DEFAULT_CTX = importlib_metadata.DistributionFinder.Context()


class _FakeDistributionFinder(importlib_metadata.DistributionFinder):
    def __init__(
        self, distributions: Iterable[importlib_metadata.Distribution]
    ) -> None:
        self._distributions = distributions

    def find_distributions(
        self,
        context: importlib_metadata.DistributionFinder.Context = _DEFAULT_CTX,
    ) -> Iterable[importlib_metadata.Distribution]:
        return self._distributions


class EntryPointFaker:
    def __init__(self) -> None:
        self._dist = _FakeDistribution()
        self._finder = _FakeDistributionFinder([self._dist])
        self._globals: Dict[str, Any] = {}
        self._enabled = False

    def enable(self) -> None:
        sys.meta_path.append(self._finder)
        self._enabled = True
        this_module = importlib.import_module(__name__)
        for name, value in self._globals.items():
            setattr(this_module, name, value)

    def disable(self) -> None:
        self._enabled = False
        sys.meta_path.remove(self._finder)
        this_module = importlib.import_module(__name__)
        for name in self._globals:
            delattr(this_module, name)

    def __enter__(self) -> "EntryPointFaker":
        self.enable()
        return self

    def __exit__(self, _type: Any, _value: Any, _tb: Any) -> None:
        self.disable()

    def add(self, name: str, value: Any, group: Any) -> None:
        if not isinstance(value, str):
            qualname = value.__qualname__
            # If the value isn't global, adopt it as a global of this module
            if "." in qualname:
                global_name = uuid.uuid4().hex
                self._globals[global_name] = value
                value = f"{__name__}:{global_name}"
                if self._enabled:
                    this_module = importlib.import_module(__name__)
                    setattr(
                        this_module, global_name, self._globals[global_name]
                    )
            else:
                value = f"{value.__module__}:{qualname}"
        if not isinstance(group, str):
            group = f"{group.__module__}.{group.__qualname__}"
        self._dist.add_entry_point(group, name, value)


class AppTest(async_case.IsolatedAsyncioTestCase):
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
        await self.lifespan_manager.__aenter__()
        self.client = httpx.AsyncClient(
            app=app_lib.APP, base_url="http://test", follow_redirects=True
        )

    async def asyncTearDown(self) -> None:
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
        session = await services.get_session()
        self.handle = await concurrency.to_thread(session.add_torrent, atp)
        # https://github.com/arvidn/libtorrent/issues/4980: add_piece() while
        # checking silently fails in libtorrent 1.2.8.
        await wait_done_checking_or_error(self.handle)
        for i, piece in enumerate(self.torrent.pieces):
            self.handle.add_piece(i, piece, 0)
