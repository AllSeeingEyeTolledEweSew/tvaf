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
from collections.abc import AsyncIterator
from collections.abc import Collection
from collections.abc import Iterable
from collections.abc import Iterator
from collections.abc import Sequence
import contextlib
import logging
from typing import Any
from typing import AsyncContextManager
from typing import Optional
from typing import Protocol
import warnings

import anyio
import libtorrent as lt

from tvaf._internal import pop_alerts as pop_alerts_lib

from . import concurrency
from . import session as session_lib

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


class _Subscription:
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

    def feed(self, alerts: Collection[lt.alert]) -> None:
        if alerts:
            self._alerts.set_result(alerts)
            self._refcount.acquire()

    def maybe_release(self) -> None:
        if self._alerts.done():
            self._alerts = asyncio.get_event_loop().create_future()
            self._refcount.release()

    async def iterator(self) -> AsyncIterator[lt.alert]:
        while True:
            for alert in await asyncio.shield(self._alerts):
                yield alert
            self.maybe_release()


class Error(Exception):
    pass


class ShutdownError(Error):
    pass


class IterAlerts(Protocol):
    def __call__(
        self,
        alert_mask: int,
        *types: _Type,
        handle: lt.torrent_handle = None,
    ) -> AsyncContextManager[AsyncIterator[lt.alert]]:
        ...


class AlertDriver:

    TIMEOUT = 10.0

    def __init__(self, *, session_service: session_lib.SessionService) -> None:
        self._session_service = session_service
        self._session = session_service.session
        self._shutdown = asyncio.get_event_loop().create_future()

        # A shared counter of how many subscriptions' iterators *may* be referencing
        # the current batch of alerts
        self._refcount = concurrency.RefCount()

        # Subscriptions indexed by their filter parameters. If type or handle is None,
        # it indicates the type/handle is not filtered, and those subscriptions should
        # receive all alerts
        self._type_to_handle_to_subs: dict[
            Optional[_Type],
            dict[Optional[lt.torrent_handle], set[_Subscription]],
        ] = collections.defaultdict(lambda: collections.defaultdict(set))

    @contextlib.contextmanager
    def _index(self, sub: _Subscription) -> Iterator:
        try:
            types: Iterable[Optional[_Type]] = sub.types
            for type_ in types or {None}:
                self._type_to_handle_to_subs[type_][sub.handle].add(sub)
            yield
        finally:
            for type_ in types or {None}:
                handle_to_subs = self._type_to_handle_to_subs[type_]
                subs = handle_to_subs[sub.handle]
                subs.discard(sub)
                if not subs:
                    del handle_to_subs[sub.handle]
                    if not handle_to_subs:
                        del self._type_to_handle_to_subs[type_]

    async def _do_raise_on_shutdown(self) -> None:
        await asyncio.shield(self._shutdown)
        raise ShutdownError()

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
    @contextlib.asynccontextmanager
    async def iter_alerts(
        self,
        alert_mask: int,
        *types: _Type,
        handle: lt.torrent_handle = None,
    ) -> AsyncIterator[AsyncIterator[lt.alert]]:
        sub = _Subscription(refcount=self._refcount, types=types, handle=handle)
        try:
            async with contextlib.AsyncExitStack() as stack:
                stack.enter_context(self._index(sub))
                stack.enter_context(self._session_service.alert_mask(alert_mask))
                watchdog_task_group = await stack.enter_async_context(
                    anyio.create_task_group()
                )
                watchdog_task_group.start_soon(self._do_raise_on_shutdown)
                yield sub.iterator()
                watchdog_task_group.cancel_scope.cancel()
        finally:
            sub.maybe_release()

    def feed(self, alerts: Sequence[lt.alert]) -> None:
        for alert in alerts:
            log_alert(alert)

        # Feed alerts to their subscriptions
        sub_to_alerts: dict[_Subscription, list[lt.alert]] = collections.defaultdict(
            list
        )
        for alert in alerts:
            lookup_types = (alert.__class__, None)
            lookup_handles: Collection[Optional[lt.torrent_handle]]
            if isinstance(alert, lt.torrent_alert):
                lookup_handles = (alert.handle, None)
            else:
                lookup_handles = (None,)
            for type_ in lookup_types:
                handle_to_subs = self._type_to_handle_to_subs.get(type_, {})
                for handle in lookup_handles:
                    subs = handle_to_subs.get(handle, ())
                    for sub in subs:
                        sub_to_alerts[sub].append(alert)

        for sub, alerts in sub_to_alerts.items():
            sub.feed(alerts)

    async def wait_safe(self) -> None:
        while True:
            try:
                with anyio.fail_after(self.TIMEOUT):
                    await self._refcount.wait_zero()
                break
            except TimeoutError:
                msg = (
                    "Alert pump timed out after "
                    f"{self.TIMEOUT}s"
                    ". Some code is blocking while handling alerts!"
                )
                warnings.warn(msg)
                # If we continue timing out, continue to pester the user
                _LOG.warning(msg)

    def shutdown(self) -> None:
        self._shutdown.set_result(None)

    async def run(self) -> None:
        _LOG.debug("AlertDriver starting up...")
        try:
            async with anyio.create_task_group() as task_group:

                async def cancel_on_shutdown() -> None:
                    await self._shutdown
                    task_group.cancel_scope.cancel()

                task_group.start_soon(cancel_on_shutdown)
                with pop_alerts_lib.get_pop_alerts(self._session) as pop_alerts:
                    while True:
                        await self.wait_safe()
                        self.feed(await pop_alerts())
        finally:
            _LOG.debug("AlertDriver shutting down")
