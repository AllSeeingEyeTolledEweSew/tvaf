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

import sys
import unittest
import unittest.mock

from tvaf import lifecycle
from tvaf import plugins

from . import lib

if sys.version_info >= (3, 8):
    pass
else:
    pass


def return_a() -> str:
    return "a"


def return_b() -> str:
    return "b"


class GetTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fake_eps = lib.EntryPointFaker()
        self.fake_eps.enable()
        self.fake_eps.add("a", return_a, "test")
        self.fake_eps.add("b", return_b, "test")

    def tearDown(self) -> None:
        self.fake_eps.disable()
        lifecycle.clear()

    def test_get(self) -> None:
        plugin_map = plugins.get("test")
        self.assertEqual(plugin_map, {"a": return_a, "b": return_b})
