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

import threading
from typing import Any

import pytest

from tvaf import concurrency


class DummyException(Exception):
    pass


async def test_return_value() -> None:
    def return_a_value() -> str:
        return "abc"

    value = await concurrency.to_thread(return_a_value)
    assert value == "abc"


async def test_exception() -> None:
    def raise_dummy() -> None:
        raise DummyException()

    with pytest.raises(DummyException):
        await concurrency.to_thread(raise_dummy)


async def test_pass_args() -> None:
    def return_my_args(*args: Any, **kwargs: Any) -> tuple[tuple, dict[str, Any]]:
        return (args, kwargs)

    (args, kwargs) = await concurrency.to_thread(return_my_args, 1, 2, 3, a=4, b=5, c=6)
    assert args == (1, 2, 3)
    assert kwargs == {"a": 4, "b": 5, "c": 6}


async def test_really_in_thread() -> None:
    outside_id = threading.get_ident()
    inside_id = await concurrency.to_thread(threading.get_ident)
    assert outside_id != inside_id
