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

import pathlib

import pytest

from tvaf import concurrency
from tvaf import config as config_lib


async def test_from_disk(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "config.json"
    await concurrency.to_thread(
        path.write_text, '{"text_field": "value", ' '"numeric_field": 123}'
    )
    config = await config_lib.Config.from_disk(path)
    assert config == config_lib.Config(text_field="value", numeric_field=123)


async def test_from_disk_invalid_json(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "config.json"
    await concurrency.to_thread(path.write_text, "invalid json")
    with pytest.raises(config_lib.InvalidConfigError):
        await config_lib.Config.from_disk(path)


async def test_write(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "config.json"
    config = config_lib.Config(text_field="value", numeric_field=123)
    await config.write_to_disk(path)
    config_text = await concurrency.to_thread(path.read_text)
    assert (
        config_text == "{\n"
        '    "numeric_field": 123,\n'
        '    "text_field": "value"\n'
        "}"
    )
