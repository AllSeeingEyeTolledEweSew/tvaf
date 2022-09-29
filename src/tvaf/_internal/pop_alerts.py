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

import asyncio
from collections.abc import Coroutine
from collections.abc import Iterator
from collections.abc import Sequence
import concurrent.futures
import contextlib
import functools
import io
import selectors
from typing import Any
from typing import Callable

import libtorrent as lt

from tvaf import ltpy
from tvaf import util


class _SelectNotSupportedError(Exception):
    pass


Type = Callable[[], Coroutine[Any, Any, Sequence[lt.alert]]]


@contextlib.contextmanager
def _get_pop_alerts_impl_event_loop(
    fp: io.RawIOBase, session: lt.session
) -> Iterator[Type]:
    have_alerts = asyncio.Event()

    async def pop_alerts() -> Sequence[lt.alert]:
        await have_alerts.wait()
        try:
            with ltpy.translate_exceptions():
                # Does not block (I think)
                alerts = session.pop_alerts()
        finally:
            # NB: the alert fd may be written again any time after pop alerts, so clear
            # the event now
            have_alerts.clear()
        assert alerts
        return alerts

    def notify() -> None:
        # This reads the entire nonblocking buffer
        fp.read()
        have_alerts.set()

    try:
        asyncio.get_event_loop().add_reader(fp, notify)
    except NotImplementedError as ex:
        raise _SelectNotSupportedError() from ex
    try:
        yield pop_alerts
    finally:
        asyncio.get_event_loop().remove_reader(fp)


# I tried an implementation with wait_for_alert() in a thread, but there's currently a
# race if wait_for_alert() and pop_alerts() are done in separate threads.
@contextlib.contextmanager
def _get_pop_alerts_impl_thread(
    fp: io.RawIOBase, session: lt.session, wait_time: float
) -> Iterator[Type]:
    assert wait_time > 0 and wait_time <= 1.0, wait_time
    # This is a long wait, so don't tie up the default executor. Use our own.
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        selector = selectors.DefaultSelector()
        with selector:
            selector.register(fp, selectors.EVENT_READ)
            select = functools.partial(selector.select, timeout=wait_time)

            async def pop_alerts() -> Sequence[lt.alert]:
                while True:
                    events = await asyncio.get_event_loop().run_in_executor(
                        executor, select
                    )
                    if events:
                        assert len(events) == 1, events
                        key, mask = events[0]
                        assert mask == selectors.EVENT_READ, events
                        assert key.fileobj == fp, events
                        break
                # This reads the entire nonblocking buffer
                fp.read()
                with ltpy.translate_exceptions():
                    # Does not block (I think)
                    alerts = session.pop_alerts()
                assert alerts
                return alerts

            yield pop_alerts
    finally:
        executor.shutdown(wait=False)


@contextlib.contextmanager
def get_pop_alerts(
    session: lt.session, *, use_thread_wait=False, thread_wait_time=1.0
) -> Iterator[Type]:
    rfile, wfile = util.selectable_pipe()

    try:
        # This will write synchronously, if there are any alerts
        with ltpy.translate_exceptions():
            session.set_alert_fd(wfile.fileno())
        try:
            with contextlib.ExitStack() as stack:
                if not use_thread_wait:
                    try:
                        yield stack.enter_context(
                            _get_pop_alerts_impl_event_loop(rfile, session)
                        )
                    except _SelectNotSupportedError:
                        use_thread_wait = True
                if use_thread_wait:
                    yield stack.enter_context(
                        _get_pop_alerts_impl_thread(rfile, session, thread_wait_time)
                    )
        finally:
            with ltpy.translate_exceptions():
                session.set_alert_fd(-1)
    finally:
        rfile.close()
        wfile.close()
