from __future__ import annotations

import asyncio
import warnings
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
    result_queue: Queue  # per-caller mailbox


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
                    task.result_queue.put(
                        await getattr(k, task.fn)(*task.args, **task.kwargs),
                    )
                except Exception as e:  # noqa: BLE001
                    task.result_queue.put(e)

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
        self._thread.start()
        self._initialized = True

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
        my_queue: Queue[Any] = Queue(maxsize=1)
        self._task_queue.put(Task(cmd, args, kwargs, my_queue))
        res = my_queue.get()
        if isinstance(res, BaseException):
            raise res
        else:
            return res


def oneshot_async_run(
    func: Callable,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
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

    t = Thread(target=run, args=(func, q, *args), kwargs=kwargs)
    t.start()
    t.join()
    res = q.get()
    if isinstance(res, BaseException):
        raise res
    else:
        return res
