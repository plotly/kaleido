"""
Kaleido is a library for generating static images from Plotly figures.

Please see the README.md for more information and a quickstart.
"""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING, Literal

from choreographer.cli import get_chrome, get_chrome_sync

from . import _sync_server
from ._page_generator import PageGenerator
from .kaleido import Kaleido, _resolve_timeout

if TYPE_CHECKING:
    from collections.abc import AsyncIterable, Iterable
    from pathlib import Path
    from typing import Any, TypeVar, Union

    from ._utils.fig_tools import Figurish, LayoutOpts

    T = TypeVar("T")
    AnyIterable = Union[AsyncIterable[T], Iterable[T]]

    from .kaleido import FigureDict

__all__ = [
    "Kaleido",
    "PageGenerator",
    "calc_fig",
    "calc_fig_sync",
    "get_chrome",
    "get_chrome_sync",
    "start_sync_server",
    "stop_sync_server",
    "write_fig",
    "write_fig_from_object",
    "write_fig_from_object_sync",
    "write_fig_sync",
]

_global_server = _sync_server.GlobalKaleidoServer()


def start_sync_server(*args: Any, silence_warnings: bool = False, **kwargs: Any):
    """
    Start a kaleido server which will process all sync generation requests.

    The kaleido server is a singleton, so it can't be opened twice. This
    function will warn you if the server is already running.

    This wrapper function takes the exact same arguments as kaleido.Kaleido(),
    except one extra: `silence_warnings`.

    Args:
        *args: all arguments `Kaleido()` would take.
        silence_warnings: (bool, default False): If True, don't emit warning if
        starting an already started server.
        **kwargs: all keyword arguments `Kaleido()` would take.

    """
    _global_server.open(*args, silence_warnings=silence_warnings, **kwargs)


def stop_sync_server(*, silence_warnings: bool = False):
    """
    Stop the kaleido server. It can be restarted.

    This function will warn you if the server is already stopped.

    Args:
        silence_warnings: (bool, default False): If True, don't emit warning if
        stopping an already stopped server.

    """
    _global_server.close(silence_warnings=silence_warnings)


async def calc_fig(
    fig: Figurish,
    opts: LayoutOpts | None = None,
    *,
    topojson: str | None = None,
    kopts: dict[str, Any] | None = None,
    timeout: float | None | Literal["auto"] = "auto",
):
    """
    Return binary for plotly figure.

    A convenience wrapper for `Kaleido.calc_fig()` which starts a `Kaleido` and
    executes `calc_fig()`.
    It takes an additional argument, `kopts`, a dictionary of arguments to pass
    to the kaleido process. See the `kaleido.Kaleido` docs. However,
    `calc_fig()` will never use more than one processor, so any `n` value will
    be overridden.

    See also the documentation for `Kaleido.calc_fig()`.

    """
    kopts = kopts or {}
    kopts.setdefault("timeout", timeout)
    kopts["n"] = 1  # should we force this?
    async with Kaleido(**kopts) as k:
        return await k.calc_fig(
            fig,
            opts=opts,
            topojson=topojson,
        )


async def write_fig(
    fig: Figurish,
    path: str | None | Path = None,
    opts: LayoutOpts | None = None,
    *,
    topojson: str | None = None,
    kopts: dict[str, Any] | None = None,
    timeout: float | None | Literal["auto"] = "auto",
    **kwargs,
):
    """
    Write a plotly figure(s) to a file.

    A convenience wrapper for `Kaleido.write_fig()` which starts a `Kaleido` and
    executes the `write_fig()`.
    It takes an additional argument, `kopts`, a dictionary of arguments to pass
    to the `Kaleido` constructor. See the `kaleido.Kaleido` docs.

    See also the documentation for `Kaleido.write_fig()`.

    """
    kopts = kopts or {}
    kopts.setdefault("timeout", timeout)
    async with Kaleido(**kopts) as k:
        return await k.write_fig(
            fig,
            path=path,
            opts=opts,
            topojson=topojson,
            **kwargs,
        )


async def write_fig_from_object(
    fig_dicts: FigureDict | AnyIterable[FigureDict],
    *,
    kopts: dict[str, Any] | None = None,
    timeout: float | None | Literal["auto"] = "auto",
    **kwargs,
):
    """
    Write a plotly figure(s) to a file specified by a dictionary or iterable of.

    A convenience wrapper for `Kaleido.write_fig_from_object()` which starts a
    `Kaleido` and executes the `write_fig_from_object()`
    It takes an additional argument, `kopts`, a dictionary of arguments to pass
    to the `Kaleido` constructor. See the `kaleido.Kaleido` docs.

    See also the documentation for `Kaleido.write_fig_from_object()`.

    """
    kopts = kopts or {}
    kopts.setdefault("timeout", timeout)
    async with Kaleido(**kopts) as k:
        return await k.write_fig_from_object(
            fig_dicts,
            **kwargs,
        )


def calc_fig_sync(
    *args: Any,
    timeout: float | None | Literal["auto"] = "auto",
    **kwargs: Any,
):
    """Call `calc_fig` but blocking."""
    if _global_server.is_running():
        if timeout != "auto":
            warnings.warn(
                "The timeout argument is ignored if using a server.",
                UserWarning,
                stacklevel=2,
            )
        return _global_server.call_function("calc_fig", *args, **kwargs)
    else:
        kwargs.setdefault("timeout", timeout)
        sync_timeout = _resolve_timeout(timeout)
        return _sync_server.oneshot_async_run(
            calc_fig,
            args=args,
            kwargs=kwargs,
            sync_timeout=sync_timeout,
        )


def write_fig_sync(
    *args: Any,
    timeout: float | None | Literal["auto"] = "auto",
    **kwargs: Any,
):
    """Call `write_fig` but blocking."""
    if _global_server.is_running():
        if timeout != "auto":
            warnings.warn(
                "The timeout argument is ignored if using a server.",
                UserWarning,
                stacklevel=2,
            )
        return _global_server.call_function("write_fig", *args, **kwargs)
    else:
        kwargs.setdefault("timeout", timeout)
        sync_timeout = _resolve_timeout(timeout)
        return _sync_server.oneshot_async_run(
            write_fig,
            args=args,
            kwargs=kwargs,
            sync_timeout=sync_timeout,
        )


def write_fig_from_object_sync(
    *args: Any,
    timeout: float | None | Literal["auto"] = "auto",
    **kwargs: Any,
):
    """Call `write_fig_from_object` but blocking."""
    if _global_server.is_running():
        if timeout != "auto":
            warnings.warn(
                "The timeout argument is ignored if using a server.",
                UserWarning,
                stacklevel=2,
            )
        return _global_server.call_function("write_fig_from_object", *args, **kwargs)
    else:
        kwargs.setdefault("timeout", timeout)
        sync_timeout = _resolve_timeout(timeout)
        return _sync_server.oneshot_async_run(
            write_fig_from_object,
            args=args,
            kwargs=kwargs,
            sync_timeout=sync_timeout,
        )
