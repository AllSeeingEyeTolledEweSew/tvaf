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

from collections.abc import AsyncIterator
import contextlib

import pytest

from tvaf import config as config_lib


class Receiver:
    def __init__(self) -> None:
        self.config = config_lib.Config()

    @contextlib.asynccontextmanager
    async def stage_config(self, config: config_lib.Config) -> AsyncIterator[None]:
        yield
        self.config = config


class DummyException(Exception):

    pass


def _raise_dummy() -> None:
    raise DummyException()


class FailReceiver:
    def __init__(self) -> None:
        self.config = config_lib.Config()

    @contextlib.asynccontextmanager
    async def stage_config(self, _config: config_lib.Config) -> AsyncIterator[None]:
        _raise_dummy()
        yield


async def test_fail() -> None:
    config = config_lib.Config(new=True)

    good_receiver = Receiver()
    fail_receiver = FailReceiver()

    # fail_receiver should cause an exception to be raised
    with pytest.raises(DummyException):
        async with config_lib.stage_config(
            config, good_receiver.stage_config, fail_receiver.stage_config
        ):
            pass

    # fail_receiver should prevent good_receiver from updating
    assert good_receiver.config == config_lib.Config()

    # Order should be independent
    with pytest.raises(DummyException):
        async with config_lib.stage_config(
            config, fail_receiver.stage_config, good_receiver.stage_config
        ):
            pass

    assert good_receiver.config == config_lib.Config()


async def test_success() -> None:
    config = config_lib.Config(new=True)

    receiver1 = Receiver()
    receiver2 = Receiver()

    async with config_lib.stage_config(
        config, receiver1.stage_config, receiver2.stage_config
    ):
        pass

    assert receiver1.config == config
    assert receiver2.config == config
