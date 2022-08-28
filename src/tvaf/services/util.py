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

import libtorrent as lt

from tvaf import caches

from .. import ltpy
from .. import services


@caches.alru_cache(maxsize=32)
async def get_torrent_info(handle: lt.torrent_handle) -> lt.torrent_info:
    async def get() -> Optional[lt.torrent_info]:
        with ltpy.translate_exceptions():
            return await asyncio.to_thread(handle.torrent_file)

    driver = await services.get_alert_driver()
    with driver.iter_alerts(
        lt.alert_category.status,
        lt.metadata_received_alert,
        lt.torrent_removed_alert,
        handle=handle,
    ) as iterator:

        async def wait_for_metadata() -> None:
            async for alert in iterator:
                if isinstance(alert, lt.metadata_received_alert):
                    break
                elif isinstance(alert, lt.torrent_removed_alert):
                    raise ltpy.InvalidTorrentHandleError.create()

        # Start the waiter immediately so alert processing can proceed
        waiter = asyncio.create_task(wait_for_metadata())
        try:
            # Check torrent_file() only after the iterator is created, to
            # ensure we see metadata_received_alert
            ti = await get()
            if ti is not None:
                return ti
            await waiter
        finally:
            waiter.cancel()
    ti = await get()
    assert ti is not None
    return ti
