# Copyright (c) 2020 AllSeeingEyeTolledEweSew
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

from typing import Any
from typing import Callable
from typing import Dict
from typing import Iterator
from typing import Optional
from typing import Union

import fastapi
import multihash
from pydantic import NonNegativeInt
import starlette.responses
import starlette.types

from tvaf import request as request_lib
from tvaf import services
from tvaf import torrent_info

router = fastapi.APIRouter(prefix="/v1", tags=["data access"])


class MultihashHex(multihash.Multihash):
    @classmethod
    def __modify_schema__(cls, field_schema: Dict[str, Any]) -> None:
        field_schema.update({"type": "string", "format": "multihash-hex"})

    @classmethod
    def __get_validators__(cls) -> Iterator[Callable[..., Any]]:
        yield cls.validate

    @classmethod
    def validate(cls, value: Union[str, bytes]) -> multihash.Multihash:
        if isinstance(value, str):
            value = bytes.fromhex(value)
        return multihash.decode(value)


class AlwaysRunStreamingResponse(starlette.responses.StreamingResponse):
    async def __call__(
        self,
        scope: starlette.types.Scope,
        receive: starlette.types.Receive,
        send: starlette.types.Send,
    ) -> None:
        try:
            super().__call__(scope, receive, send)
        except Exception:
            # background gets run in the base class if there are no errors
            await self.background()


def reader(request: request_lib.Request) -> Iterator[bytes]:
    while True:
        mview = request.read(timeout=60)
        if mview is None:
            raise TimeoutError()
        data = bytes(mview)
        if not data:
            return
        yield data


@router.api_route("/btmh/{btmh}/i/{file_index}", methods=("GET", "HEAD"))
def read_file(
    btmh: MultihashHex, file_index: NonNegativeInt, request: fastapi.Request
):
    if btmh.func != multihash.Func.sha1:
        raise fastapi.HTTPException(
            status_code=fastapi.status.HTTP_404_NOT_FOUND,
            detail="only sha1 info-hashes are known",
        )

    start, stop = torrent_info.get_file_bounds(btmh, file_index)
    configure_atp = torrent_info.get_configure_atp(btmh)

    headers = {
        "Content-Type": "application/octet-stream",
        "Content-Length": stop - start,
    }

    iterator: Iterator[bytes] = iter(())
    cleanup: Optional[starlette.background.BackgroundTask] = None
    if request.method == "GET":
        request_service = services.get_request_service()
        request = request_service.add_request(
            info_hash=btmh.digest.hex(),
            start=start,
            stop=stop,
            mode=request_lib.Mode.READ,
            configure_atp=configure_atp,
        )
        iterator = reader(request)
        cleanup = starlette.background.BackgroundTask(
            request_service.discard_request, request
        )

    return AlwaysRunStreamingResponse(
        iterator, headers=headers, background=cleanup
    )
