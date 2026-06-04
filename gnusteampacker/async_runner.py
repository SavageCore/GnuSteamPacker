"""
Run asyncio coroutines from GTK's main thread via a background event loop thread.
Callbacks are always delivered on the GLib main loop (safe for UI updates).
"""

import asyncio
import threading
from collections.abc import Callable, Coroutine
from typing import Any

from gi.repository import GLib

_loop: asyncio.AbstractEventLoop | None = None
_thread: threading.Thread | None = None
_lock = threading.Lock()


def _get_loop() -> asyncio.AbstractEventLoop:
    global _loop, _thread
    with _lock:
        if _loop is None or not _loop.is_running():
            _loop = asyncio.new_event_loop()
            _thread = threading.Thread(target=_loop.run_forever, daemon=True, name="gsp-async")
            _thread.start()
    return _loop


def run(coro: Coroutine, done_cb: Callable[[Any, Exception | None], None] | None = None) -> None:
    """Submit a coroutine to the background loop. done_cb(result, exc) fires on the GLib loop."""
    loop = _get_loop()

    async def wrapper():
        try:
            result = await coro
            if done_cb:
                GLib.idle_add(done_cb, result, None)
        except Exception as exc:
            if done_cb:
                GLib.idle_add(done_cb, None, exc)

    asyncio.run_coroutine_threadsafe(wrapper(), loop)
