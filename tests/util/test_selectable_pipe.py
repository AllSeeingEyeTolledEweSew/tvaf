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

import select
import selectors
import threading
import time

from tvaf import util


def test_select_write_before() -> None:
    rfile, wfile = util.selectable_pipe()
    wfile.write(b"\0")
    result = select.select((rfile,), (), ())
    assert result == ([rfile], [], [])
    rfile.close()
    wfile.close()


def test_select_write_from_thread() -> None:
    rfile, wfile = util.selectable_pipe()

    def write_from_thread() -> None:
        # Is there a way to synchronize this?
        time.sleep(0.1)
        wfile.write(b"\0")

    threading.Thread(target=write_from_thread).start()
    result = select.select((rfile,), (), ())
    assert result == ([rfile], [], [])
    rfile.close()
    wfile.close()


def test_default_selector_write_before() -> None:
    rfile, wfile = util.selectable_pipe()
    wfile.write(b"\0")
    selector = selectors.DefaultSelector()
    selector.register(rfile, selectors.EVENT_READ)
    events = selector.select()
    assert len(events) == 1
    key, _ = events[0]
    assert key.fileobj == rfile
    rfile.close()
    wfile.close()


def test_default_selector_write_from_thread() -> None:
    rfile, wfile = util.selectable_pipe()

    def write_from_thread() -> None:
        # Is there a way to synchronize this?
        time.sleep(0.1)
        wfile.write(b"\0")

    selector = selectors.DefaultSelector()
    selector.register(rfile, selectors.EVENT_READ)
    threading.Thread(target=write_from_thread).start()
    events = selector.select()
    assert len(events) == 1
    key, _ = events[0]
    assert key.fileobj == rfile
    rfile.close()
    wfile.close()
