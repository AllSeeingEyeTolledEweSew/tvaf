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

from __future__ import annotations

import asyncio
import sys

from tvaf import config as config_lib
from tvaf import services

from . import lib


def setUpModule() -> None:
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


class GetTest(lib.AppTest, lib.TestCase):
    async def test_get(self) -> None:
        r = await self.client.get("/config")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), await asyncio.wait_for(services.get_config(), 5))


class PostTest(lib.AppTest, lib.TestCase):
    async def test_get(self) -> None:
        config = config_lib.Config(await asyncio.wait_for(services.get_config(), 5))
        config["test"] = "test"
        r = await self.client.post("/config", json=config)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(
            (await asyncio.wait_for(services.get_config(), 5))["test"], "test"
        )
