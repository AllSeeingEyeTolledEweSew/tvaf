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

import pytest

from tvaf import config as config_lib


def test_get_int() -> None:
    config = config_lib.Config(key=123)
    assert config.get_int("key") == 123


def test_get_int_missing() -> None:
    config = config_lib.Config()
    assert config.get_int("key") is None


def test_get_int_invalid() -> None:
    config = config_lib.Config(key="not an int")
    with pytest.raises(config_lib.InvalidConfigError):
        config.get_int("key")


def test_get_str() -> None:
    config = config_lib.Config(key="value")
    assert config.get_str("key") == "value"


def test_get_str_missing() -> None:
    config = config_lib.Config()
    assert config.get_str("key") is None


def test_get_str_invalid() -> None:
    config = config_lib.Config(key=123)
    with pytest.raises(config_lib.InvalidConfigError):
        config.get_str("key")


def test_get_bool() -> None:
    config = config_lib.Config(key=True)
    assert config.get_bool("key") is True


def test_get_bool_missing() -> None:
    config = config_lib.Config()
    assert config.get_bool("key") is None


def test_get_bool_invalid() -> None:
    config = config_lib.Config(key=1)
    with pytest.raises(config_lib.InvalidConfigError):
        config.get_bool("key")


def test_require_int() -> None:
    config = config_lib.Config(key=123)
    assert config.require_int("key") == 123


def test_require_int_missing() -> None:
    config = config_lib.Config()
    with pytest.raises(config_lib.InvalidConfigError):
        config.require_int("key")


def test_require_int_invalid() -> None:
    config = config_lib.Config(key="not an int")
    with pytest.raises(config_lib.InvalidConfigError):
        config.require_int("key")


def test_require_str() -> None:
    config = config_lib.Config(key="value")
    assert config.require_str("key") == "value"


def test_require_str_missing() -> None:
    config = config_lib.Config()
    with pytest.raises(config_lib.InvalidConfigError):
        config.require_str("key")


def test_require_str_invalid() -> None:
    config = config_lib.Config(key=123)
    with pytest.raises(config_lib.InvalidConfigError):
        config.require_str("key")


def test_require_bool() -> None:
    config = config_lib.Config(key=True)
    assert config.require_bool("key") is True


def test_require_bool_missing() -> None:
    config = config_lib.Config()
    with pytest.raises(config_lib.InvalidConfigError):
        config.require_bool("key")


def test_require_bool_invalid() -> None:
    config = config_lib.Config(key=1)
    with pytest.raises(config_lib.InvalidConfigError):
        config.require_bool("key")
