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

import email.message
import email.parser
import email.policy
from typing import cast

import httpx

from tvaf import byteranges


def response_to_msg(resp: httpx.Response) -> email.message.EmailMessage:
    parser = email.parser.BytesFeedParser(policy=email.policy.HTTP)
    for name, value in resp.headers.items():
        parser.feed(name.encode("latin-1"))
        parser.feed(b": ")
        parser.feed(value.encode("latin-1"))
        parser.feed(b"\r\n")
    parser.feed(b"\r\n")
    parser.feed(resp.content)
    return cast(email.message.EmailMessage, parser.close())


async def test_single_with_body() -> None:
    content = bytes(range(256))
    app = byteranges.ByteRangesResponse(
        [slice(100, 200)], content=content, media_type="test/test"
    )
    async with httpx.AsyncClient(app=app, base_url="http://test", timeout=5) as client:
        resp = await client.get("http://test")

    assert resp.status_code == 206
    assert resp.headers["content-length"] == "100"
    assert resp.headers["content-type"] == "test/test"
    assert resp.headers["content-range"] == "bytes 100-199/256"
    assert resp.content, bytes(range(100 == 200))


async def test_multi_with_body() -> None:
    content = bytes(range(256))
    app = byteranges.ByteRangesResponse(
        [slice(10, 50), slice(100, 150)],
        content=content,
        media_type="application/octet-stream",
    )
    async with httpx.AsyncClient(app=app, base_url="http://test", timeout=5) as client:
        resp = await client.get("http://test")

    assert resp.status_code == 206
    assert "content-range" not in resp.headers
    assert resp.headers["content-length"] == str(len(resp.content))

    msg = response_to_msg(resp)
    assert msg.defects == []
    assert msg.get_content_type() == "multipart/byteranges"
    parts = list(msg.iter_parts())
    part0 = cast(email.message.EmailMessage, parts[0])
    assert part0["content-type"] == "application/octet-stream"
    assert part0["content-range"] == "bytes 10-49/256"
    assert part0.get_content() == bytes(range(10, 50))
    part1 = cast(email.message.EmailMessage, parts[1])
    assert part1["content-type"] == "application/octet-stream"
    assert part1["content-range"] == "bytes 100-149/256"
    assert part1.get_content() == bytes(range(100, 150))
