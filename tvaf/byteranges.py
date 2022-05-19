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

"""Utilities for serving HTTP byte-range requests according to RFC 7233."""
from __future__ import annotations

import re
from typing import Any
from typing import Sequence
import uuid

from starlette.datastructures import Headers
from starlette.datastructures import MutableHeaders
import starlette.responses
from starlette.types import Receive
from starlette.types import Scope
from starlette.types import Send

from . import concurrency

_RANGE_RE = re.compile(r"(\d+)?-(\d+)?")


def parse_bytes_range(value: str) -> Sequence[slice]:
    """Parses an HTTP Range header with "bytes" units.

    This parses an HTTP Range header according RFC 7233.

    Args:
        value: The value of the Range: header.

    Returns:
        A Sequence of slice objects. There will be one slice per byte range
        in the input, and they will be returned in input order. Either the

    Raises:
        ValueError: value doesn't start with "bytes=", or otherwise doesn't
        conform to the Byte Ranges section of RFC 7233.

    Examples:
        >>> parse_bytes_range("bytes=0-499")
        [slice(0, 500)]
        >>> parse_bytes_range("bytes=0-499,500-999")
        [slice(0, 500), slice(500, 1000)]
        >>> parse_bytes_range("bytes=-500")
        [slice(-500, None)]
        >>> parse_bytes_range("bytes=9500-")
        [slice(9500, None)]
    """
    if not value.startswith("bytes="):
        raise ValueError(value)
    result: list[slice] = []
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


def _get_multipart_delim(headers_200: Headers, boundary: bytes, s: slice) -> bytes:
    part_headers = _get_part_headers(headers_200, s)
    result = [b"--", boundary, b"\r\n"]
    for name, value in part_headers.items():
        result.extend((name.encode("latin-1"), b": ", value.encode("latin-1"), b"\r\n"))
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
    """An ASGI Response class for streaming HTTP 206 (Partial Content).

    ByteRangesResponse generates appropriate responses for RFC 7233 Range
    Requests.

    The slices attribute describes the byte ranges of the parts to be sent in
    order. ByteRangesResponse will only send parts as described by slices; it
    does not reorder or merge them.

    If there's only one part, then the response will include a Content-Range
    header, and the body will just be the requested part.

    If there are multiple parts, then ByteRangesResponse will send a
    multipart/byteranges payload according to RFC 7233. The Content-Type of
    each body part will be the Content-Type supplied in the headers (or
    media_type) arguments. It will use a UUID for the content boundary,
    uniquely generated for each response.

    You can supply the content argument to serve parts of some pre-generated
    content. You can also override the send_range() method to dynamically get
    or generate the content parts. Note that even for generated content, you
    must supply the complete set of byte ranges in the slices argument.

    The headers argument, and media_type, must be the headers that would be
    sent in a 200 (OK) response. The Content-Type must be the type of the
    content being split into parts. If Content-Length would have been sent
    in a 200 (OK) response, it is required here.

    ByteRangesResponse computes an accurate Content-Length for the response
    payload, even for generated content and even where an overall
    Content-Length is not supplied in the headers argument. The response's
    Content-Length is deterministic based on the byte ranges to be sent, so it
    is computed and sent before send_range() is ever called.

    ByteRangesResponse will detect client disconnection and cancel its
    response-streaming task, similar to starlette's StreamingResponse.

    Attributes:
        slices: The byte ranges of content to send.
        boundary: The boundary string used in the multipart response payload.
    """

    def __init__(
        self,
        slices: Sequence[slice],
        *,
        headers: dict = None,
        content: Any = None,
        media_type: str = None,
    ) -> None:
        """Constructs a ByteRangesResponse.

        Args:
            slices: The byte ranges of content to send. The stop attribute of
                each slice must not be negative. If Content-Length is not
                supplied, then the stop attribute of each slice must not be
                None.
            headers: The headers that would have been sent in a 200 (OK)
                response.
            content: The overall content to be split into parts. Must be
                convertible to bytes.
            media_type: The Content-Type of the overall content to be split
                into parts. Only required if Content-Type does not occur in
                headers.
        """
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
            self.headers["content-range"] = _get_content_range(self.headers_200, s)
            self.headers["content-length"] = str(s.stop - s.start)
        else:
            self.headers[
                "content-type"
            ] = f'multipart/byteranges; boundary="{self.boundary}"'
            self.headers["content-length"] = str(
                _get_multipart_length(self.headers_200, self.raw_boundary, self.slices)
            )

    async def _listen_for_disconnect(self, receive: Receive) -> None:
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                break

    async def _stream_response(self, scope: Scope, send: Send) -> None:
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
                delim = _get_multipart_delim(self.headers_200, self.raw_boundary, s)
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
        """Sends a part of the overall content.

        This internal method gets called by the ASGI app to send a part of the
        content. It will be called once for each slice in the slices attribute,
        in order.

        This sends just the part of the content specified by the slice. It
        doesn't send the headers or the multipart/byteranges scaffolding.

        Override this method to stream dynamically-retrieved or
        dynamically-generated content.

        This method should use the send callback to send one or more
        "http.response.body" messages (or equivalents). The "more_body"
        parameter should always be True. The total amount of data sent must be
        equal to the length of the slice.

        Args:
            scope: The ASGI scope structure.
            send: The ASGI send callback.
            s: A byte range representing the content to be sent.
        """
        await send(
            {
                "type": "http.response.body",
                "body": await self._get_range(s),
                "more_body": True,
            }
        )

    async def _get_range(self, s: slice) -> Any:
        return self.body[s]

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Invokes the response as an ASGI app.

        Args:
            scope: The ASGI scope structure.
            receive: The ASGI receive callback.
            send: The ASGI send callback.
        """
        await concurrency.first(
            (self._stream_response(scope, send), self._listen_for_disconnect(receive))
        )
