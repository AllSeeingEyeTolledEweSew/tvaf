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
from typing import Any
from typing import Callable
from typing import Optional

import anyio


# Design notes: This class exists to bridge the gap between the ASGI "lifespan.startup"
# and "lifespan.shutdown" events, and the notion of a long-running main task. I tried
# to write a simple lifespan context manager:
#
# async def lifespan():
#    global global_task_group
#    with create_task_group() as global_task_group:
#        run_startup_plugins()
#        yield
#        run_shutdown_plugins()
#
# async def startup_event():
#    global global_lifecycle
#    global_lifecycle = lifecycle()
#    await global_lifecycle.__aenter__()
#
# async def shutdown_event():
#    await global_lifecycle.__aexit__(None, None, None)
#
# However the anyio TaskGroup does not like to change tasks between aenter and aexit.
# We need the following event-based implementation, which must use
# asyncio.create_task().
class MainTaskLifespanAdaptor:
    def __init__(
        self,
        do_startup: Callable[[], Coroutine[Any, Any, Any]],
        do_shutdown: Callable[[], Coroutine[Any, Any, Any]],
    ) -> None:
        self._tasks = anyio.create_task_group()
        self._task: Optional[asyncio.Task] = None
        self._startup_event = asyncio.get_event_loop().create_future()
        self._shutdown_event = asyncio.get_event_loop().create_future()
        self.do_startup = do_startup
        self.do_shutdown = do_shutdown

    async def startup(self) -> None:
        assert self._task is None
        self._task = asyncio.create_task(self._run(), name="tvaf main task")
        done, _ = await asyncio.wait(
            (self._task, self._startup_event), return_when=asyncio.FIRST_COMPLETED
        )
        # propagate exception
        for task in done:
            task.result()

    async def shutdown(self) -> None:
        assert self._task is not None
        self._shutdown_event.set_result(None)
        await self._task

    def cancel(self, msg: str = None) -> None:
        self._startup_event.cancel(msg=msg)
        if self._task is not None:
            self._task.cancel(msg=msg)

    async def _run(self) -> None:
        assert self._task is asyncio.current_task()
        assert not self._shutdown_event.done()
        async with self._tasks:
            await self.do_startup()
            self._startup_event.set_result(None)
            await self._shutdown_event
            await self.do_shutdown()

    def start_soon(
        self,
        func: Callable[..., Coroutine[Any, Any, Any]],
        *args: Any,
        name: str = None
    ) -> None:
        self._tasks.start_soon(func, *args, name=name)
