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

from __future__ import annotations

import asyncio
import threading
from typing import Any
from typing import Iterator
import unittest

from tvaf import concurrency

from . import lib


class DummyException(Exception):
    pass


class ToThreadTest(unittest.IsolatedAsyncioTestCase):
    async def test_return_value(self) -> None:
        def return_a_value() -> str:
            return "abc"

        value = await concurrency.to_thread(return_a_value)
        self.assertEqual(value, "abc")

    async def test_exception(self) -> None:
        def raise_dummy() -> None:
            raise DummyException()

        with self.assertRaises(DummyException):
            await concurrency.to_thread(raise_dummy)

    async def test_pass_args(self) -> None:
        def return_my_args(*args: Any, **kwargs: Any) -> tuple[tuple, dict[str, Any]]:
            return (args, kwargs)

        (args, kwargs) = await concurrency.to_thread(
            return_my_args, 1, 2, 3, a=4, b=5, c=6
        )
        self.assertEqual(args, (1, 2, 3))
        self.assertEqual(kwargs, {"a": 4, "b": 5, "c": 6})

    async def test_really_in_thread(self) -> None:
        outside_id = threading.get_ident()
        inside_id = await concurrency.to_thread(threading.get_ident)
        self.assertNotEqual(outside_id, inside_id)


class IterInThreadTest(unittest.IsolatedAsyncioTestCase):
    async def test_return_value(self) -> None:
        def iterator() -> Iterator[int]:
            yield 1
            yield 2
            yield 3

        aiterator = concurrency.iter_in_thread(iterator())
        values = [value async for value in aiterator]
        self.assertEqual(values, [1, 2, 3])

    async def test_exception(self) -> None:
        def iterator() -> Iterator[int]:
            yield 1
            raise DummyException()

        aiterator = concurrency.iter_in_thread(iterator())
        with self.assertRaises(DummyException):
            async for value in aiterator:
                pass

    async def test_really_in_thread(self) -> None:
        def iterator() -> Iterator[int]:
            yield threading.get_ident()

        outside_ids = [threading.get_ident()]
        aiterator = concurrency.iter_in_thread(iterator())
        inside_ids = [value async for value in aiterator]
        self.assertNotEqual(outside_ids, inside_ids)

    async def test_small_batch_size(self) -> None:
        def iterator() -> Iterator[int]:
            yield from range(100)

        aiterator = concurrency.iter_in_thread(iterator(), batch_size=1)
        values = [value async for value in aiterator]
        self.assertEqual(values, list(range(100)))

    async def test_large_batch_size(self) -> None:
        def iterator() -> Iterator[int]:
            yield 1

        aiterator = concurrency.iter_in_thread(iterator(), batch_size=1000000)
        values = [value async for value in aiterator]
        self.assertEqual(values, [1])


class WaitFirstTest(unittest.IsolatedAsyncioTestCase):
    async def test_first_completed(self) -> None:
        async def noop() -> None:
            pass

        forever = asyncio.get_event_loop().create_future()
        await asyncio.wait_for(concurrency.wait_first((noop(), forever)), 5)
        self.assertTrue(forever.done())
        self.assertTrue(forever.cancelled())

    async def test_exception(self) -> None:
        async def raise_dummy() -> None:
            raise DummyException()

        forever = asyncio.get_event_loop().create_future()
        with self.assertRaises(DummyException):
            await asyncio.wait_for(concurrency.wait_first((raise_dummy(), forever)), 5)
        self.assertTrue(forever.done())
        self.assertTrue(forever.cancelled())

    async def test_cancel(self) -> None:
        # Cancel the *outer* task, only once the inner task is really running
        forever = asyncio.get_event_loop().create_future()

        async def cancel_task(task: asyncio.Future) -> None:
            task.cancel()
            await forever

        current_task = asyncio.current_task()
        assert current_task is not None
        with self.assertRaises(asyncio.CancelledError):
            await concurrency.wait_first((forever, cancel_task(current_task)))
        self.assertTrue(forever.done())
        self.assertTrue(forever.cancelled())


class RefCountTest(unittest.IsolatedAsyncioTestCase):
    async def test_count(self) -> None:
        refcount = concurrency.RefCount()
        self.assertEqual(refcount.count(), 0)
        refcount.acquire()
        self.assertEqual(refcount.count(), 1)
        refcount.release()
        self.assertEqual(refcount.count(), 0)

    async def test_release_below_zero(self) -> None:
        refcount = concurrency.RefCount()
        with self.assertRaises(ValueError):
            refcount.release()

    async def test_wait_zero(self) -> None:
        refcount = concurrency.RefCount()
        await refcount.wait_zero()
        refcount.acquire()

        async def do_release() -> None:
            refcount.release()

        task = asyncio.create_task(do_release())
        await refcount.wait_zero()
        await task


class AcachedTest(unittest.IsolatedAsyncioTestCase):
    async def test_cache(self) -> None:
        cache: dict = {}
        call_count = 0

        @concurrency.acached(cache)
        async def func(*args: Any, **kwargs: Any) -> None:
            nonlocal call_count
            call_count += 1

        # Initial calls
        await func(1, a=2)
        await func(3, a=4)
        self.assertEqual(call_count, 2)

        # Subsequent calls should be cached
        call_count = 0
        await func(1, a=2)
        await func(3, a=4)
        self.assertEqual(call_count, 0)

        # We should be able to clear the cache
        cache.clear()
        await func(1, a=2)
        await func(3, a=4)
        self.assertEqual(call_count, 2)


class AcachedPropertyTest(unittest.IsolatedAsyncioTestCase):
    async def test_acached_property(self) -> None:
        class Dummy:
            def __init__(self) -> None:
                self.calls = 0

            @concurrency.acached_property
            async def prop(self) -> str:
                self.calls += 1
                return "value"

        dummy = Dummy()
        first = dummy.prop
        second = dummy.prop
        self.assertEqual(await first, "value")
        self.assertEqual(await second, "value")
        self.assertEqual(dummy.calls, 1)


class AsCompletedTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        async def returner() -> int:
            return 0

        self.returner = returner()
        self.forever = asyncio.get_event_loop().create_future()

    async def test_cleanup(self) -> None:
        async for future in concurrency.as_completed([self.forever, self.returner]):
            self.assertEqual(await future, 0)
            break

        # Test that the forever-waiting future is eventually cancelled
        for _ in lib.loop_until_timeout(10):
            # NB: for the async generator to be cleaned up, it must be marked
            # for cleanup by garbage collection, then __aexit__ is invoked by
            # the event loop
            await asyncio.sleep(0)
            if self.forever.done():
                break


class AsCompletedCtxTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        async def returner() -> int:
            return 0

        self.returner = returner()
        self.forever = asyncio.get_event_loop().create_future()

    async def test_cleanup(self) -> None:
        with concurrency.as_completed_ctx([self.forever, self.returner]) as iterator:
            for future in iterator:
                self.assertEqual(await future, 0)
                break

        # Test that the forever-waiting future was canceled immediately
        self.assertTrue(self.forever.done())
