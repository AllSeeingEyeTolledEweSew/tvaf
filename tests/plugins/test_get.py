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

from tests import epfake
from tvaf import plugins


def return_a() -> str:
    return "a"


def return_b() -> str:
    return "b"


def test_get(entry_point_faker: epfake.EntryPointFaker) -> None:
    def return_a() -> str:
        return "a"

    def return_b() -> str:
        return "b"

    entry_point_faker.add("a", return_a, "test")
    entry_point_faker.add("b", return_b, "test")

    plugin_map = plugins.get("test")

    assert plugin_map == {"a": return_a, "b": return_b}
