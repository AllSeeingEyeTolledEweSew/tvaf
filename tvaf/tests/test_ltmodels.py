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
import base64
import datetime
import errno
import json
import sys
import unittest

import libtorrent as lt
import pydantic

from tvaf import concurrency
from tvaf import ltmodels

from . import lib


def setUpModule() -> None:
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


class ErrorCodeTest(unittest.TestCase):
    def test_from_orm(self) -> None:
        ec = lt.error_code()
        ec.assign(errno.ECANCELED, lt.generic_category())
        value = ltmodels.ErrorCode.from_orm(ec)
        self.assertEqual(
            value,
            ltmodels.ErrorCode(
                category="generic",
                value=errno.ECANCELED,
                message="Operation canceled",
            ),
        )


class Sha1HashTest(unittest.TestCase):
    class Model(pydantic.BaseModel):
        sha1: ltmodels.Sha1Hash

    def test_orm(self) -> None:
        sha1 = lt.sha1_hash(b"\xaa" * 20)
        model = self.Model(sha1=sha1)
        self.assertEqual(model.sha1, "aa" * 20)

    def test_lower(self) -> None:
        model = self.Model(sha1="AA" * 20)
        self.assertEqual(model.sha1, "aa" * 20)

    def test_length(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            self.Model(sha1="AA")

    def test_format(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            self.Model(sha1="qq" * 20)


class Sha256HashTest(unittest.TestCase):
    class Model(pydantic.BaseModel):
        sha256: ltmodels.Sha256Hash

    def test_orm(self) -> None:
        sha256 = lt.sha256_hash(b"\xaa" * 32)
        model = self.Model(sha256=sha256)
        self.assertEqual(model.sha256, "aa" * 32)

    def test_lower(self) -> None:
        model = self.Model(sha256="AA" * 32)
        self.assertEqual(model.sha256, "aa" * 32)

    def test_length(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            self.Model(sha256="AA")

    def test_format(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            self.Model(sha256="qq" * 32)


class InfoHashesTest(unittest.TestCase):
    def test_from_orm(self) -> None:
        ih = lt.info_hash_t(lt.sha1_hash(b"\xaa" * 20), lt.sha256_hash(b"\xbb" * 32))
        info_hashes = ltmodels.InfoHashes.from_orm(ih)
        self.assertEqual(info_hashes, ltmodels.InfoHashes(v1="aa" * 20, v2="bb" * 32))

    def test_from_orm_v1(self) -> None:
        ih = lt.info_hash_t(lt.sha1_hash(b"\xaa" * 20))
        info_hashes = ltmodels.InfoHashes.from_orm(ih)
        self.assertEqual(info_hashes, ltmodels.InfoHashes(v1="aa" * 20))

    def test_from_orm_v2(self) -> None:
        ih = lt.info_hash_t(lt.sha256_hash(b"\xbb" * 32))
        info_hashes = ltmodels.InfoHashes.from_orm(ih)
        self.assertEqual(info_hashes, ltmodels.InfoHashes(v2="bb" * 32))


class Base64Test(unittest.TestCase):
    class Model(ltmodels.BaseModel):
        base64: ltmodels.Base64

    def test_bytes(self) -> None:
        model = self.Model(base64=b"abc123\xff")
        self.assertEqual(model.base64, b"abc123\xff")

    def test_base64_good(self) -> None:
        model = self.Model(base64=base64.b64encode(b"abc123\xff").decode())
        self.assertEqual(model.base64, b"abc123\xff")

    def test_base64_bad(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            self.Model(base64="!@#$%^&*()")

    def test_to_json(self) -> None:
        model = self.Model(base64=b"abc123\xff")
        self.assertEqual(model.json(), '{"base64": "YWJjMTIz/w=="}')

    def test_parse_json(self) -> None:
        model = self.Model.parse_raw('{"base64": "YWJjMTIz/w=="}')
        self.assertEqual(model, self.Model(base64=b"abc123\xff"))


class TorrentStatusTest(lib.AppTestWithTorrent, lib.TestCase):
    @unittest.skip("flaky")
    async def test_status(self) -> None:
        orm = await concurrency.to_thread(self.handle.status, flags=0x7FFFFFFF)
        status = ltmodels.TorrentStatus.from_orm(orm)

        status_dict = json.loads(status.json())
        # test unstable parts
        self.assertIsInstance(status_dict.pop("added_time"), int)
        self.assertIsInstance(status_dict.pop("completed_time"), int)
        datetime.datetime.fromisoformat(status_dict.pop("last_download"))
        self.assertEqual(status_dict.pop("save_path"), self.tempdir.name)
        self.assert_golden_json(status_dict)
