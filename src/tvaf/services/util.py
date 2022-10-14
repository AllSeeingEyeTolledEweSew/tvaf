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
from typing import Optional

import anyio
import libtorrent as lt

from tvaf import caches
from tvaf import driver as driver_lib

from .. import ltpy


@caches.alru_cache(maxsize=32)
async def get_torrent_info(
    *,
    handle: lt.torrent_handle,
    iter_alerts: driver_lib.IterAlerts,
    _waiting_for_alert: asyncio.Future = None,
) -> lt.torrent_info:
    async def get() -> Optional[lt.torrent_info]:
        with ltpy.translate_exceptions():
            return await asyncio.to_thread(handle.torrent_file)

    async with iter_alerts(
        lt.alert_category.status,
        lt.metadata_received_alert,
        lt.torrent_removed_alert,
        handle=handle,
    ) as iterator:
        async with anyio.create_task_group() as tasks:

            async def handle_alerts() -> None:
                async for alert in iterator:
                    tasks.cancel_scope.cancel()

            tasks.start_soon(handle_alerts)

            # Check torrent_file() only after the iterator is created, to
            # ensure we see metadata_received_alert
            ti = await get()
            if ti is not None:
                tasks.cancel_scope.cancel()
                return ti
            if _waiting_for_alert is not None:
                _waiting_for_alert.set_result(None)
    ti = await get()
    assert ti is not None
    return ti
