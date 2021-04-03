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

import sys
from typing import Any
import unittest
import unittest.mock

from tvaf import lifecycle
from tvaf import plugins

if sys.version_info >= (3, 8):
    import importlib.metadata as importlib_metadata
else:
    import importlib_metadata


def return_a() -> str:
    return "a"


def return_b() -> str:
    return "b"


def raise_pass() -> str:
    raise plugins.Pass()


# There doesn't seem to be an API to add new distributions or create
# sys.meta_path finders to return fake distributions. Instead we patch out
# importlib.metadata.entry_points().
class EntryPointMockerTest(unittest.TestCase):
    def setUp(self) -> None:
        # Ensure this becomes a copied Dict[str, Tuple[EntryPoint, ...]]
        self.entry_points = {
            group: tuple(values)
            for (group, values) in importlib_metadata.entry_points().items()
        }
        self.patch = unittest.mock.patch.object(
            importlib_metadata, "entry_points", return_value=self.entry_points
        )
        self.patch.start()

    def add_entry(self, name: str, value: Any, group: Any) -> None:
        if not isinstance(value, str):
            value = f"{value.__module__}:{value.__qualname__}"
        if not isinstance(group, str):
            group = f"{group.__module__}.{group.__qualname__}"
        entry = importlib_metadata.EntryPoint(
            name=name, value=value, group=group
        )
        self.entry_points.setdefault(group, ())
        self.entry_points[group] += (entry,)

    def tearDown(self) -> None:
        self.patch.stop()
        lifecycle.clear()


class GetEntryPointsTest(EntryPointMockerTest):
    def setUp(self) -> None:
        super().setUp()
        self.add_entry("a", return_a, "test")
        self.add_entry("b", return_b, "test")

    def test_order(self) -> None:
        self.assertEqual(
            list(plugins.get_entry_points("test")),
            [
                importlib_metadata.EntryPoint(
                    "a", f"{__name__}:return_a", "test"
                ),
                importlib_metadata.EntryPoint(
                    "b", f"{__name__}:return_b", "test"
                ),
            ],
        )

    def test_no_entry_points(self) -> None:
        self.assertEqual(list(plugins.get_entry_points("does_not_exist")), [])


class LoadEntryPointsTest(EntryPointMockerTest):
    def setUp(self) -> None:
        super().setUp()
        self.add_entry("a", return_a, "test")
        self.add_entry("b", return_b, "test")

    def test_get_plugins(self) -> None:
        plugin_list = plugins.load_entry_points("test")
        values = [plugin() for plugin in plugin_list]
        self.assertEqual(values, ["a", "b"])


class CallFirstTest(EntryPointMockerTest):
    def test_last_returns(self) -> None:
        self.add_entry("a", raise_pass, "test")
        self.add_entry("b", return_a, "test")
        self.assertEqual(plugins.call_first("test"), "a")

    def test_first_returns(self) -> None:
        self.add_entry("a", return_a, "test")
        self.add_entry("b", raise_pass, "test")
        self.assertEqual(plugins.call_first("test"), "a")

    def test_all_raise_pass(self) -> None:
        self.add_entry("a", raise_pass, "test")
        self.add_entry("b", raise_pass, "test")
        with self.assertRaises(plugins.Pass):
            plugins.call_first("test")

    def test_empty(self) -> None:
        with self.assertRaises(plugins.Pass):
            plugins.call_first("test")
