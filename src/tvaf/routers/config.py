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

import logging
from typing import Any

import fastapi
import starlette.responses

from .. import config as config_lib
from .. import services

ROUTER = fastapi.APIRouter(prefix="/config", tags=["server config"])

_LOG = logging.getLogger(__name__)


@ROUTER.get("/", response_class=starlette.responses.JSONResponse)
async def get() -> config_lib.Config:
    return await services.get_config()


@ROUTER.post("/")
async def post(config: dict[str, Any]) -> None:
    await services.set_config(config_lib.Config(config))
