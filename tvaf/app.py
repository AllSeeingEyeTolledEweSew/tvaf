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

"""The tvaf ASGI app.

Example:
    Run tvaf with your favorite ASGI server.

        python -m uvicorn tvaf.app:APP
"""
from __future__ import annotations

import fastapi

from . import services
from .routers import config as config_router
from .routers import data as data_router
from .routers import torrent as torrent_router

APP = fastapi.FastAPI()
"""The tvaf ASGI app."""

APP.include_router(config_router.ROUTER)
APP.include_router(data_router.ROUTER)
APP.include_router(torrent_router.ROUTER)


@APP.on_event("startup")
async def _startup() -> None:
    await services.startup()


@APP.on_event("shutdown")
async def _shutdown() -> None:
    await services.shutdown()
