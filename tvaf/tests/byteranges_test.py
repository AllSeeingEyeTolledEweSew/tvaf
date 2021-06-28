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

import email.message
import email.parser
import email.policy
from typing import cast
import unittest

import requests
import starlette.testclient

from tvaf import byteranges


class ParseBytesRangeTest(unittest.TestCase):
    def test_empty(self) -> None:
        with self.assertRaises(ValueError):
            byteranges.parse_bytes_range("")

    def test_not_bytes(self) -> None:
        with self.assertRaises(ValueError):
            byteranges.parse_bytes_range("timestamps=")

    def test_no_ranges(self) -> None:
        with self.assertRaises(ValueError):
            byteranges.parse_bytes_range("bytes=")

    def test_basic(self) -> None:
        slices = byteranges.parse_bytes_range("bytes=1-2")
        self.assertEqual(slices, [slice(1, 3)])

    def test_tail(self) -> None:
        slices = byteranges.parse_bytes_range("bytes=1-")
        self.assertEqual(slices, [slice(1, None)])

    def test_suffix(self) -> None:
        slices = byteranges.parse_bytes_range("bytes=-5")
        self.assertEqual(slices, [slice(-5)])

    def test_dash(self) -> None:
        with self.assertRaises(ValueError):
            byteranges.parse_bytes_range("bytes=-")

    def test_multi(self) -> None:
        slices = byteranges.parse_bytes_range("bytes=1-2, 3-4")
        self.assertEqual(slices, [slice(1, 3), slice(3, 5)])
        slices = byteranges.parse_bytes_range("bytes=1-2, 1-")
        self.assertEqual(slices, [slice(1, 3), slice(1, None)])
        slices = byteranges.parse_bytes_range("bytes=1-2, -5")
        self.assertEqual(slices, [slice(1, 3), slice(-5)])

    def test_whitespace(self) -> None:
        slices = byteranges.parse_bytes_range("bytes=1-2, 3-4")
        self.assertEqual(slices, [slice(1, 3), slice(3, 5)])
        slices = byteranges.parse_bytes_range("bytes=  1-2,  3-4  ")
        self.assertEqual(slices, [slice(1, 3), slice(3, 5)])
        slices = byteranges.parse_bytes_range("bytes=1-2,3-4")
        self.assertEqual(slices, [slice(1, 3), slice(3, 5)])


def response_to_msg(resp: requests.Response) -> email.message.EmailMessage:
    parser = email.parser.BytesFeedParser(policy=email.policy.HTTP)
    for name, value in resp.headers.items():
        parser.feed(name.encode("latin-1"))
        parser.feed(b": ")
        parser.feed(value.encode("latin-1"))
        parser.feed(b"\r\n")
    parser.feed(b"\r\n")
    parser.feed(resp.content)
    return cast(email.message.EmailMessage, parser.close())


class ByteRangesResponseTest(unittest.TestCase):
    def test_single_with_body(self) -> None:
        content = bytes(range(256))
        app = byteranges.ByteRangesResponse(
            [slice(100, 200)], content=content, media_type="test/test"
        )
        client = starlette.testclient.TestClient(app)
        resp = client.get("/")
        self.assertEqual(resp.status_code, 206)
        self.assertEqual(resp.headers["content-length"], "100")
        self.assertEqual(resp.headers["content-type"], "test/test")
        self.assertEqual(resp.headers["content-range"], "bytes 100-199/256")
        self.assertEqual(resp.content, bytes(range(100, 200)))

    def test_multi_with_body(self) -> None:
        content = bytes(range(256))
        app = byteranges.ByteRangesResponse(
            [slice(10, 50), slice(100, 150)],
            content=content,
            media_type="application/octet-stream",
        )
        client = starlette.testclient.TestClient(app)
        resp = client.get("/")
        self.assertEqual(resp.status_code, 206)
        self.assertNotIn("content-range", resp.headers)
        self.assertEqual(
            resp.headers["content-length"], str(len(resp.content))
        )

        msg = response_to_msg(resp)
        self.assertEqual(msg.defects, [])
        self.assertEqual(msg.get_content_type(), "multipart/byteranges")
        parts = list(msg.iter_parts())
        part0 = cast(email.message.EmailMessage, parts[0])
        self.assertEqual(part0["content-type"], "application/octet-stream")
        self.assertEqual(part0["content-range"], "bytes 10-49/256")
        self.assertEqual(part0.get_content(), bytes(range(10, 50)))
        part1 = cast(email.message.EmailMessage, parts[1])
        self.assertEqual(part1["content-type"], "application/octet-stream")
        self.assertEqual(part1["content-range"], "bytes 100-149/256")
        self.assertEqual(part1.get_content(), bytes(range(100, 150)))
