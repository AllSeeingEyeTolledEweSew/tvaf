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


from tvaf import config as config_lib
from tvaf import services

from . import lib


class GetTest(lib.AppTest, lib.TestCase):
    async def test_get(self) -> None:
        r = await self.client.get("/v1/config")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), await services.get_config())


class PostTest(lib.AppTest, lib.TestCase):
    async def test_get(self) -> None:
        config = config_lib.Config(await services.get_config())
        config["test"] = "test"
        r = await self.client.post("/v1/config", json=config)
        self.assertEqual(r.status_code, 200)
        self.assertEqual((await services.get_config())["test"], "test")
