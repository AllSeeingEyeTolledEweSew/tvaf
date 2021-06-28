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

import re
from typing import Any
from typing import Dict
from typing import List
from typing import Sequence
import uuid

import starlette.concurrency
from starlette.datastructures import Headers
from starlette.datastructures import MutableHeaders
import starlette.responses
from starlette.types import Receive
from starlette.types import Scope
from starlette.types import Send

_RANGE_RE = re.compile(r"(\d+)?-(\d+)?")


def parse_bytes_range(value: str) -> Sequence[slice]:
    if not value.startswith("bytes="):
        raise ValueError(value)
    result: List[slice] = []
    for spec in value[6:].split(","):
        m = _RANGE_RE.match(spec.strip())
        if not m:
            raise ValueError(value)
        start, end = m.group(1), m.group(2)
        if not start and not end:
            raise ValueError(value)
        if not start:
            result.append(slice(-int(end)))
        else:
            result.append(slice(int(start), int(end) + 1 if end else None))
    return result


def _normalize(headers_200: Headers, s: slice) -> slice:
    assert s.stop is None or s.stop >= 0, s.stop
    if "content-length" in headers_200:
        return slice(*s.indices(int(headers_200["content-length"])))
    else:
        assert s.stop is not None
        return slice(*s.indices(s.stop))


def _get_content_range(headers_200: Headers, s: slice) -> str:
    s = _normalize(headers_200, s)
    total = headers_200.get("content-length", "*")
    return f"bytes {s.start}-{s.stop - 1}/{total}"


def _get_part_headers(headers_200: Headers, s: slice) -> Headers:
    result = MutableHeaders()
    if "content-type" in headers_200:
        result["content-type"] = headers_200["content-type"]
    result["content-range"] = _get_content_range(headers_200, s)
    return result


def _get_multipart_delim(
    headers_200: Headers, boundary: bytes, s: slice
) -> bytes:
    part_headers = _get_part_headers(headers_200, s)
    result = [b"--", boundary, b"\r\n"]
    for name, value in part_headers.items():
        result.extend(
            (name.encode("latin-1"), b": ", value.encode("latin-1"), b"\r\n")
        )
    result.append(b"\r\n")
    return b"".join(result)


def _get_multipart_length(
    headers_200: Headers, boundary: bytes, slices: Sequence[slice]
) -> int:
    result = 0
    for s in slices:
        result += 2 + len(boundary) + 2  # --boundary\r\n
        part_headers = _get_part_headers(headers_200, s)
        for name, value in part_headers.items():
            result += len(name) + 2 + len(value) + 2  # name: value\r\n
        result += 2  # \r\n
        s = _normalize(headers_200, s)
        result += s.stop - s.start  # <data>
        result += 2  # \r\n
    result += 2 + len(boundary) + 2  # --boundary--
    return result


class ByteRangesResponse(starlette.responses.Response):
    def __init__(
        self,
        slices: Sequence[slice],
        *,
        headers: Dict = None,
        content: Any = None,
        media_type: str = None,
    ) -> None:
        super().__init__(
            status_code=206,
            headers=headers,
            content=content,
            media_type=media_type,
        )
        assert slices
        self.slices = slices
        self.headers_200 = Headers(self.headers)
        self.boundary = str(uuid.uuid4())
        self.raw_boundary = self.boundary.encode("latin-1")
        if len(self.slices) == 1:
            s = _normalize(self.headers_200, self.slices[0])
            self.headers["content-range"] = _get_content_range(
                self.headers_200, s
            )
            self.headers["content-length"] = str(s.stop - s.start)
        else:
            self.headers[
                "content-type"
            ] = f'multipart/byteranges; boundary="{self.boundary}"'
            self.headers["content-length"] = str(
                _get_multipart_length(
                    self.headers_200, self.raw_boundary, self.slices
                )
            )

    async def listen_for_disconnect(self, receive: Receive) -> None:
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                break

    async def stream_response(self, scope: Scope, send: Send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": self.status_code,
                "headers": self.raw_headers,
            }
        )
        if len(self.slices) == 1:
            await self.send_range(scope, send, self.slices[0])
            await send(
                {
                    "type": "http.response.body",
                    "body": b"",
                    "more_body": False,
                }
            )
        else:
            for i, s in enumerate(self.slices):
                delim = _get_multipart_delim(
                    self.headers_200, self.raw_boundary, s
                )
                if i != 0:
                    delim = b"\r\n" + delim
                await send(
                    {
                        "type": "http.response.body",
                        "body": delim,
                        "more_body": True,
                    }
                )
                await self.send_range(scope, send, s)
            close_parts = [b"--", self.raw_boundary, b"--"]
            if self.slices:
                close_parts.insert(0, b"\r\n")
            close = b"".join(close_parts)
            await send(
                {
                    "type": "http.response.body",
                    "body": close,
                    "more_body": False,
                }
            )

    async def send_range(self, scope: Scope, send: Send, s: slice) -> None:
        await send(
            {
                "type": "http.response.body",
                "body": await self.get_range(s),
                "more_body": True,
            }
        )

    async def get_range(self, s: slice) -> Any:
        return self.body[s]

    async def __call__(
        self, scope: Scope, receive: Receive, send: Send
    ) -> None:
        await starlette.concurrency.run_until_first_complete(
            (self.stream_response, {"scope": scope, "send": send}),
            (self.listen_for_disconnect, {"receive": receive}),
        )
