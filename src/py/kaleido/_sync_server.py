from __future__ import annotations

import asyncio
import atexit
import os
import signal
import subprocess
import time
import warnings
from functools import partial
from queue import Queue
from threading import Thread
from typing import TYPE_CHECKING, NamedTuple

from .kaleido import Kaleido

if TYPE_CHECKING:
    from typing import Any, Callable


class Task(NamedTuple):
    fn: str
    args: Any
    kwargs: Any


class _BadFunctionName(BaseException):
    """For use when programmed poorly."""


class GlobalKaleidoServer:
    _instance = None

    async def _server(self, *args, **kwargs):
        async with Kaleido(*args, **kwargs) as k:  # multiple processor? Enable GPU?
            while True:
                task = self._task_queue.get()  # thread dies if main thread dies
                if task is None:
                    self._task_queue.task_done()
                    return
                if not hasattr(k, task.fn):
                    raise _BadFunctionName(f"Kaleido has no attribute {task.fn}")
                try:
                    self._return_queue.put(
                        await getattr(k, task.fn)(*task.args, **task.kwargs),
                    )
                except Exception as e:  # noqa: BLE001
                    self._return_queue.put(e)

                self._task_queue.task_done()

    def __new__(cls):
        # Create the singleton on first instantiation
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False  # noqa: SLF001
        return cls._instance

    def is_running(self):
        return self._initialized

    def open(self, *args: Any, silence_warnings=False, **kwargs: Any) -> None:
        """Initialize the singleton with three values."""
        if self.is_running():
            if not silence_warnings:
                warnings.warn(
                    "Server already open.",
                    RuntimeWarning,
                    stacklevel=2,
                )
            return
        coroutine = self._server(*args, **kwargs)
        self._thread: Thread = Thread(
            target=asyncio.run,
            args=(coroutine,),
            daemon=True,
        )
        self._task_queue: Queue[Task | None] = Queue()
        self._return_queue: Queue[Any] = Queue()
        self._thread.start()
        self._initialized = True
        close = partial(self.close, silence_warnings=True)
        atexit.register(close)

    def close(self, *, silence_warnings=False):
        """Reset the singleton back to an uninitialized state."""
        if not self.is_running():
            if not silence_warnings:
                warnings.warn(
                    "Server already closed.",
                    RuntimeWarning,
                    stacklevel=2,
                )
            return
        self._task_queue.put(None)
        self._thread.join()
        del self._thread
        del self._task_queue
        del self._return_queue
        self._initialized = False

    def call_function(self, cmd: str, *args: Any, **kwargs: Any):
        """
        Call any function on the singleton Kaleido object.

        Preferred functions would be: `calc_fig`, `write_fig`, and
        `write_fig_from_object`. Methods that doesn't exist will raise a
        BaseException.

        Args:
            cmd (str): the name of the method to call
            args (Any): the method's arguments
            kwargs (Any): the method's keyword arguments

        """
        if not self.is_running():
            raise RuntimeError("Can't call function on stopped server.")
        if kwargs.pop("kopts", None):
            warnings.warn(
                "The kopts argument is ignored if using a server.",
                UserWarning,
                stacklevel=3,
            )
        self._task_queue.put(Task(cmd, args, kwargs))
        self._task_queue.join()
        res = self._return_queue.get()
        if isinstance(res, BaseException):
            raise res
        else:
            return res


def oneshot_async_run(
    func: Callable,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    *,
    sync_timeout: float | None = None,
) -> Any:
    """
    Run a thread to execute a single function.

    Used by _sync functions in
    `__init__` to ensure their async loop is separate from the users main
    one.

    Args:
        func: the function to run
        args: a tuple of arguments to pass
        kwargs: a dictionary of keyword arguments to pass

    """
    q: Queue[Any] = Queue(maxsize=1)

    def run(func, q, *args, **kwargs):
        # func is a closure
        try:
            q.put(asyncio.run(func(*args, **kwargs)))
        except BaseException as e:  # noqa: BLE001
            q.put(e)

    def _pid_exists(pid: int) -> bool:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def _kill_child_chrome_processes() -> None:
        try:
            result = subprocess.run(
                ["ps", "-Ao", "pid=,ppid=,command="],
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError:
            return

        children: dict[int, list[int]] = {}
        commands: dict[int, str] = {}

        for line in result.stdout.splitlines():
            if not line.strip():
                continue
            parts = line.strip().split(maxsplit=2)
            if len(parts) < 2:
                continue
            try:
                pid = int(parts[0])
                ppid = int(parts[1])
            except ValueError:
                continue
            command = parts[2] if len(parts) > 2 else ""
            children.setdefault(ppid, []).append(pid)
            commands[pid] = command

        descendants: set[int] = set()
        stack = [os.getpid()]
        while stack:
            current = stack.pop()
            for child in children.get(current, []):
                if child in descendants:
                    continue
                descendants.add(child)
                stack.append(child)

        chrome_pids = [
            pid
            for pid in descendants
            if "chrome" in commands.get(pid, "").lower()
            or "chromium" in commands.get(pid, "").lower()
        ]

        for pid in chrome_pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                continue

        if chrome_pids:
            time.sleep(0.5)

        for pid in chrome_pids:
            if not _pid_exists(pid):
                continue
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                continue

    t = Thread(
        target=run,
        args=(func, q, *args),
        kwargs=kwargs,
        daemon=sync_timeout is not None,
    )
    t.start()
    t.join(timeout=sync_timeout)
    if t.is_alive():
        if sync_timeout is not None:
            _kill_child_chrome_processes()
        raise TimeoutError(
            "Kaleido sync call exceeded the timeout; Chrome termination attempted.",
        )
    res = q.get()
    if isinstance(res, BaseException):
        raise res
    else:
        return res
