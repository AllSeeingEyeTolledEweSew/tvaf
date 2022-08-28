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
import collections
from collections.abc import AsyncGenerator
from collections.abc import Collection
from collections.abc import Iterable
from collections.abc import Iterator
import contextlib
import logging
from typing import Any
from typing import Optional
import warnings

import libtorrent as lt

from . import concurrency
from . import ltpy
from . import session as session_lib
from . import util

_LOG = logging.getLogger(__name__)


def log_alert(
    alert: lt.alert, message: str = "", args: Iterable[Any] = (), method=None
) -> None:
    prefix = "%s"
    prefix_args = [alert.__class__.__name__]
    torrent_name = getattr(alert, "torrent_name", None)
    error = getattr(alert, "error", None)
    if torrent_name and torrent_name not in alert.message():
        prefix += ": %s"
        prefix_args += [torrent_name]
    if alert.message():
        prefix += ": %s"
        prefix_args += [alert.message()]
    if error and error.value():
        prefix += " [%s (%s %d)]"
        prefix_args += [
            error.message(),
            error.category().name(),
            error.value(),
        ]
        if method is None:
            method = _LOG.error
    if method is None:
        method = _LOG.debug

    if message:
        message = prefix + ": " + message
    else:
        message = prefix

    args = prefix_args + list(args)

    method(message, *args)


_Type = type[lt.alert]


class _Iterator:
    def __init__(
        self,
        *,
        refcount: concurrency.RefCount,
        types: Collection[_Type],
        handle: Optional[lt.torrent_handle],
    ) -> None:
        self.types = types
        self.handle = handle
        self._refcount = refcount

        self._alerts: asyncio.Future[
            Iterable[lt.alert]
        ] = asyncio.get_event_loop().create_future()
        self._exc = asyncio.get_event_loop().create_future()

    def feed(self, alerts: Collection[lt.alert]) -> None:
        if alerts:
            self._alerts.set_result(alerts)
            self._refcount.acquire()

    def maybe_release(self) -> None:
        if self._alerts.done():
            self._alerts = asyncio.get_event_loop().create_future()
            self._refcount.release()

    def set_exception(self, exc: BaseException) -> None:
        if not self._exc.done():
            self._exc.set_exception(exc)
            # Don't warn if exception was never retrieved
            self._exc.exception()

    async def iterator(self) -> AsyncGenerator[lt.alert, None]:
        while True:
            await concurrency.wait_first(
                (asyncio.shield(self._alerts), asyncio.shield(self._exc))
            )
            alerts = self._alerts.result()
            for alert in alerts:
                yield alert
            self.maybe_release()


class AlertDriver:

    TIMEOUT = 10.0

    def __init__(self, *, session_service: session_lib.SessionService) -> None:
        self._session_service = session_service
        self._session = session_service.session

        # A shared counter of how many iterators *may* be referencing the
        # current batch of alerts
        self._refcount = concurrency.RefCount()
        # The current batch of alerts, used for iter_alerts(start=...).
        self._alerts: list[lt.alert] = []
        self._alert_to_index: dict[lt.alert, int] = {}

        # Iterators indexed by their filter parameters. If type or handle is
        # None, it indicates the type/handle is not filtered, and those
        # iterators should receive all alerts
        self._type_to_handle_to_iters: dict[
            Optional[_Type],
            dict[Optional[lt.torrent_handle], set[_Iterator]],
        ] = collections.defaultdict(lambda: collections.defaultdict(set))

        self._rfile, self._wfile = util.selectable_pipe()

    def _index(self, it: _Iterator) -> None:
        types: Iterable[Optional[_Type]] = it.types
        for type_ in types or {None}:
            self._type_to_handle_to_iters[type_][it.handle].add(it)

    def _deindex(self, it: _Iterator) -> None:
        types: Iterable[Optional[_Type]] = it.types
        for type_ in types or {None}:
            handle_to_iters = self._type_to_handle_to_iters[type_]
            iters = handle_to_iters[it.handle]
            iters.discard(it)
            if not iters:
                del handle_to_iters[it.handle]
                if not handle_to_iters:
                    del self._type_to_handle_to_iters[type_]

    def _all_iters(self) -> Iterator[_Iterator]:
        for handle_to_iters in self._type_to_handle_to_iters.values():
            for iters in handle_to_iters.values():
                yield from iters

    # Design notes: ideally this would just return an AsyncGenerator. But if
    # the generator references alerts and is then "dropped" (canceled or
    # break-ed out of), we don't want to wait for gc to clean it up, as this
    # would block alert processing.
    # We could return a "naive" AsyncGenerator and require callers to clean
    # up explicitly with @contextlib.closing or similar. However we want
    # iterators to see alerts posted in some well-defined context. The only
    # options I can think of are:
    # 1. Iterators see alerts posted after they're created. This means the
    #    returned generator needs to be subscribed to alerts (and reference
    #    them) immediately, before the first __anext__(). This is brittle, as
    #    dropped iterators would block alert processing forever. This could be
    #    mitigated with finalizers, but these add a lot of complexity.
    # 2. We provide a callback to be called once the iterator has been
    #    subscribed (from the first __anext__()). This makes common usage
    #    awkward.
    @contextlib.contextmanager
    def iter_alerts(
        self,
        alert_mask: int,
        *types: _Type,
        handle: lt.torrent_handle = None,
        raise_if_removed=True,
    ) -> Iterator[AsyncGenerator[lt.alert, None]]:
        it = _Iterator(refcount=self._refcount, types=types, handle=handle)
        if handle and raise_if_removed:

            async def check() -> None:
                assert handle is not None
                if not await asyncio.to_thread(
                    ltpy.handle_in_session, handle, self._session
                ):
                    it.set_exception(ltpy.InvalidTorrentHandleError.create())

            asyncio.create_task(check())
        try:
            self._index(it)
            self._session_service.inc_alert_mask(alert_mask)
            yield it.iterator()
        finally:
            it.maybe_release()
            self._deindex(it)
            self._session_service.dec_alert_mask(alert_mask)

    async def pump_alerts(self) -> None:
        await self._refcount.wait_zero()

        with ltpy.translate_exceptions():
            # Does not block (I think)
            self._alerts = self._session.pop_alerts()
        self._alert_to_index = {alert: i for i, alert in enumerate(self._alerts)}

        for alert in self._alerts:
            log_alert(alert)

        # Feed alerts to their iterators
        iter_alerts: dict[_Iterator, list[lt.alert]] = collections.defaultdict(list)
        for alert in self._alerts:
            lookup_types = (alert.__class__, None)
            lookup_handles: Collection[Optional[lt.torrent_handle]]
            if isinstance(alert, lt.torrent_alert):
                lookup_handles = (alert.handle, None)
            else:
                lookup_handles = (None,)
            for type_ in lookup_types:
                handle_to_iters = self._type_to_handle_to_iters.get(type_, {})
                for handle in lookup_handles:
                    iters = handle_to_iters.get(handle, ())
                    for it in iters:
                        iter_alerts[it].append(alert)

        for it, alerts in iter_alerts.items():
            it.feed(alerts)

    async def _pump_alerts_from_notify(self) -> None:
        # Looping forever is better than nothing (?)
        while True:
            try:
                await asyncio.wait_for(self.pump_alerts(), self.TIMEOUT)
                break
            except asyncio.TimeoutError:
                msg = (
                    "Alert pump timed out after "
                    f"{self.TIMEOUT}s"
                    ". Some code is blocking while handling alerts!"
                )
                warnings.warn(msg)
                # If we continue timing out, continue to pester the user
                _LOG.warning(msg)

    def start(self) -> None:
        def notify():
            # This reads the entire nonblocking buffer
            self._rfile.read()
            asyncio.create_task(self._pump_alerts_from_notify())

        asyncio.get_event_loop().add_reader(self._rfile, notify)
        # This *does* fire immediately, if there are pending alerts
        self._session.set_alert_fd(self._wfile.fileno())

    def close(self) -> None:
        for it in self._all_iters():
            it.set_exception(asyncio.CancelledError())
        self._session.set_alert_fd(-1)
        asyncio.get_event_loop().remove_reader(self._rfile)
        self._rfile.close()
        self._wfile.close()

    async def wait_closed(self) -> None:
        await self._refcount.wait_zero()
