"""the kaleido module kaleido.py provides the main classes for the kaleido package."""

from __future__ import annotations

import asyncio
import os
import warnings
from collections import deque
from collections.abc import AsyncIterable, Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Literal, TypedDict, cast, overload

import choreographer as choreo
import logistro
from choreographer.errors import ChromeNotFoundError
from choreographer.utils import TmpDirectory

from . import _profiler, _utils
from ._kaleido_tab import _KaleidoTab
from ._page_generator import PageGenerator
from ._utils import fig_tools, path_tools

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, ValuesView
    from types import TracebackType
    from typing import (
        Any,
        Literal,
        TypeVar,
        Union,
    )

    from typing_extensions import NotRequired, Required, TypeAlias, TypeGuard

    T = TypeVar("T")
    AnyIterable: TypeAlias = Union[Iterable[T], AsyncIterable[T]]  # not runtime

    # Python typing has no intersection type for Iterable & Sized, so list the
    # sized iterables that _conform_tabs accepts
    Listish: TypeAlias = Union[tuple[T], list[T], ValuesView[T]]

    class FigureDict(TypedDict):
        """The type a fig_dicts returns for `write_fig_from_object`."""

        fig: Required[fig_tools.Figurish]
        path: NotRequired[None | str | Path]
        opts: NotRequired[fig_tools.LayoutOpts | None]
        topojson: NotRequired[None | str]


def _is_figuredict(obj: Any) -> TypeGuard[FigureDict]:
    return isinstance(obj, dict) and "fig" in obj


_logger = logistro.getLogger(__name__)

_TIMEOUT_ENV_VAR = "KALEIDO_RENDER_TIMEOUT"
_DEFAULT_TIMEOUT = 90.0
_AUTO_TIMEOUT = "auto"


def _resolve_timeout(timeout: float | None | Literal["auto"]) -> float | None:
    if timeout != _AUTO_TIMEOUT:
        return timeout

    env_value = os.getenv(_TIMEOUT_ENV_VAR)
    if env_value is None or env_value.strip() == "":
        return _DEFAULT_TIMEOUT

    normalized = env_value.strip().lower()
    if normalized in {"none", "null", "off"}:
        return None

    try:
        return float(normalized)
    except ValueError:
        warnings.warn(
            f"Invalid {_TIMEOUT_ENV_VAR} value '{env_value}', "
            f"falling back to default timeout of {_DEFAULT_TIMEOUT}s.",
            RuntimeWarning,
            stacklevel=2,
        )
        return _DEFAULT_TIMEOUT


# Show a warning if the installed Plotly version
# is incompatible with this version of Kaleido
_utils.warn_incompatible_plotly()

try:
    from plotly.utils import PlotlyJSONEncoder  # type: ignore[import-untyped] # noqa: I001
    from choreographer import channels

    channels.register_custom_encoder(PlotlyJSONEncoder)
    _logger.debug("Successfully registered PlotlyJSONEncoder.")
except ImportError as e:
    _logger.debug(f'Couldn\'t import plotly due to "{e!s}" - skipping.')


class Kaleido(choreo.Browser):
    """
    The Kaleido object provides a browser to render and write plotly figures.

    It provides methods to render said figures, and manages any number of tabs
    in a work queue. Start it one of a few equal ways:

    async with Kaleido() as k:
        ...

    # or

    k = await Kaleido()
    ...
    await k.close()

    # or

    k = Kaleido()
    await k.open()
    ...
    await.k.close()
    """

    tabs_ready: asyncio.Queue[_KaleidoTab]
    """A queue of tabs ready to process a kaleido figure."""
    _main_render_coroutines: set[asyncio.Task]
    # technically Tasks, user sees coroutines
    profiler: deque[_profiler.WriteCall]

    _total_tabs: int
    _html_tmp_dir: None | TmpDirectory

    ### KALEIDO LIFECYCLE FUNCTIONS ###

    def __init__(  # noqa: PLR0913
        self,
        # *args: Any, force named vars for all choreographer passthrough
        n: int = 1,
        timeout: float | None | Literal["auto"] = _AUTO_TIMEOUT,
        page_generator: None | PageGenerator | str | Path = None,
        plotlyjs: str | Path | None = None,
        mathjax: str | Path | Literal[False] | None = None,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> None:
        """
        Create a new Kaleido process for rendering plotly figures.

        Args:
            *args (Any):
                Passed through to underlying choreographer.Browser()
            n (int, optional):
                Number of processors to use (parallelization). Defaults to 1.

            timeout (float | None | "auto", optional):
                Number of seconds to wait to render any one image. None for no
                timeout. Defaults to "auto", which uses the
                KALEIDO_RENDER_TIMEOUT environment variable when set, otherwise
                falls back to 90 seconds.

            page_generator (None | PageGenerator | str | Path, optional):
                A PageGenerator object can be used for deep customization of the
                plotly template page. This is for development use. You can also
                pass a string or path directly to an index.html, or any object
                with a `generate_index()->str function that prints an HTML
                ppage. Defaults to None.

            plotlyjs (str | Path | None, optional):
                A path or URL to a plotly.js file. Defaults to None- which means
                to use the plotly.js included with your version of plotly.py or
                if not installed, the latest version available via CDN.

            mathjax (str | Path | Literal[False] | None, optional):
                A path or URL to a mathjax.js file. If False, mathjax is
                disabled. If not provided, Kaleido will use MathJax v3 via
                CDN.

            headers (dict[str, str] | None, optional):
                A dictionary of extra HTTP headers to send with every request
                made by the browser (e.g. {"Referer": "https://example.com/"}).
                Uses the Chrome DevTools Protocol Network.setExtraHTTPHeaders.
                Defaults to None.

            **kwargs (Any):
                Additional keyword arguments passed through to the underlying
                Choreographer.browser constructor. Notable options include
                `headless=False` (show window), `enable_sandbox=True` (turn on
                sandboxing), and `enable_gpu=True` which will allow use of the
                GPU. The defaults for these options are True, False, and False
                respectively.

        """
        # State variables
        self._main_render_coroutines = set()
        self.tabs_ready = asyncio.Queue(maxsize=0)
        self._total_tabs = 0  # tabs properly registered
        self._html_tmp_dir = None
        self.profiler: deque[_profiler.WriteCall] = deque(maxlen=5)

        # Kaleido Config
        if page_generator and (plotlyjs is not None or mathjax is not None):
            raise ValueError(
                "page_generator cannot be set with mathjax or plotlyjs",
            )

        page = page_generator
        self._timeout = _resolve_timeout(timeout)
        self._n = n
        self._plotlyjs = plotlyjs
        self._mathjax = mathjax
        self._headers = headers

        # Diagnostic
        _logger.debug(f"Timeout: {self._timeout}")

        try:
            super().__init__(**kwargs)
        except ChromeNotFoundError:
            msg = (
                "Kaleido v1 and later requires Chrome to be installed. "
                "To install Chrome, use the CLI command `kaleido_get_chrome`, "
                "or from Python, use either `await kaleido.get_chrome()` "
                "or `kaleido.get_chrome_sync()`."
            )
            # a path the user set explicitly is the likelier cause
            if browser_path := kwargs.get("path"):
                msg = f"No browser found at path={str(browser_path)!r}. {msg}"
            elif browser_path := os.environ.get("BROWSER_PATH"):
                msg = f"No browser found at BROWSER_PATH={browser_path!r}. {msg}"
            # overwriting the error entirely. (diagnostics)
            raise ChromeNotFoundError(msg) from None

        # save this for open() because it requires close()
        self._saved_page_arg = page

    async def open(self):
        """Build page and temporary file if we need one, then open browser."""
        page = self._saved_page_arg
        del self._saved_page_arg

        if isinstance(page, (Path, str)):
            if (_p := path_tools.get_path(page)).is_file():
                self._index = _p.as_uri()
            else:
                raise FileNotFoundError(f"{page!s} does not exist.")
        elif not page or hasattr(page, "generate_index"):
            self._html_tmp_dir = TmpDirectory(sneak=self.is_isolated())
            index = self._html_tmp_dir.path / "index.html"
            self._index = index.as_uri()
            if not page:
                page = PageGenerator(plotly=self._plotlyjs, mathjax=self._mathjax)
            with index.open("w") as f:  # is blocking but ok
                f.write(page.generate_index())
        else:
            raise TypeError(
                "page_generator must be one of: None, a"
                " PageGenerator, or a file path to an index.html.",
            )
        await super().open()

    async def _create_kaleido_tab(self) -> None:
        tab = await super().create_tab(
            url="",
            window=True,
        )
        await self._conform_tabs([tab])

    async def _conform_tabs(self, tabs: Listish[choreo.Tab] | None = None) -> None:
        if not tabs:
            tabs = self.tabs.values()
        _logger.info(f"Conforming {len(tabs)} to {self._index}")
        for i, tab in enumerate(tabs):
            _logger.debug2(f"Subscribing * to tab: {tab}.")
            tab.subscribe("*", _utils.event_printer(f"tab-{i!s}: Event Dump:"))

        kaleido_tabs = [_KaleidoTab(tab, headers=self._headers) for tab in tabs]

        await asyncio.gather(*(tab.navigate(self._index) for tab in kaleido_tabs))

        for ktab in kaleido_tabs:
            self._total_tabs += 1
            await self.tabs_ready.put(ktab)

    async def populate_targets(self) -> None:
        """
        Override the browser populate_targets to ensure the correct page.

        Is called automatically during initialization, and should only be called
        once.
        """
        await super().populate_targets()
        await self._conform_tabs()
        needed_tabs = self._n - len(self.tabs)
        if not needed_tabs:
            return

        await asyncio.gather(
            *(self._create_kaleido_tab() for _ in range(needed_tabs)),
        )

    async def close(self) -> None:
        """Close the browser."""
        if self._html_tmp_dir:
            _logger.debug(f"Cleaning up {self._html_tmp_dir}")
            self._html_tmp_dir.clean()
        else:
            _logger.debug("No kaleido._html_tmp_dir to clean up.")

        await super().close()

        # cancellation only happens if crash/early
        _logger.info("Cancelling tasks.")
        for task in self._main_render_coroutines:
            if not task.done():
                task.cancel()

        _logger.info("Exiting Kaleido/Choreo.")

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool | None:
        """Close the browser."""
        _logger.info("Waiting for all cleanups to finish.")

        # render "tasks" are coroutines, so use is awaiting them

        await asyncio.gather(*self._main_render_coroutines, return_exceptions=True)

        _logger.info("Exiting Kaleido.")
        return await super().__aexit__(exc_type, exc_value, exc_tb)

    ### TAB MANAGEMENT FUNCTIONS ####

    async def _get_kaleido_tab(self) -> _KaleidoTab:
        _logger.info(f"Getting tab from queue (has {self.tabs_ready.qsize()})")
        if not self._total_tabs:
            raise RuntimeError(
                "Before generating a figure, you must await `k.open()`.",
            )
        tab = await self.tabs_ready.get()
        _logger.info(f"Got {tab.tab.target_id[:4]}")
        return tab

    async def _return_kaleido_tab(self, tab: _KaleidoTab) -> None:
        _logger.info(f"Reloading tab {tab.tab.target_id[:4]} before return.")
        await tab.reload()
        _logger.info(
            f"Putting tab {tab.tab.target_id[:4]} back (queue size: "
            f"{self.tabs_ready.qsize()}).",
        )
        await self.tabs_ready.put(tab)
        _logger.debug(f"{tab.tab.target_id[:4]} put back.")

    # _retuner_task MUST calculate full_path before it awaits
    async def _render_task(
        self,
        fig_arg: FigureDict,
        *,
        topojson: str | None,
        _write: bool,
        profiler: _profiler.WriteCall,
        stepper: bool,
    ) -> None | bytes:
        spec = fig_tools.coerce_for_js(
            fig_arg.get("fig"),
            fig_arg.get("path", None),
            fig_arg.get("opts", None),
        )

        if _write:
            full_path = path_tools.determine_path(
                fig_arg.get("path", None),
                spec["data"],
                spec["format"],  # should just take spec
            )
            full_path.touch()  # claim our name
        else:
            full_path = None

        tab = await self._get_kaleido_tab()

        render_prof = _profiler.RenderTaskProfile(
            spec,
            full_path if _write else None,
            tab.tab.target_id,
        )
        render_prof.profile_log.tick("acquired tab")
        profiler.renders.append(render_prof)

        try:
            img_bytes = await asyncio.wait_for(
                tab._calc_fig(  # noqa: SLF001
                    spec,
                    topojson=topojson,
                    render_prof=render_prof,
                    stepper=stepper,
                ),
                self._timeout,
            )
            if _write and full_path:
                render_prof.profile_log.tick("starting file write")
                await _utils.to_thread(full_path.write_bytes, img_bytes)
                render_prof.profile_log.tick("file write done")
                return None
            else:
                return img_bytes
        except BaseException as e:
            render_prof.profile_log.tick("errored out")
            if _write and full_path:
                full_path.unlink()  # failure, no write
            render_prof.error = e
            raise
        finally:
            render_prof.profile_log.tick("returning tab")
            await self._return_kaleido_tab(tab)
            render_prof.profile_log.tick("tab returned")

    ### API ###
    @overload
    async def write_fig_from_object(
        self,
        fig_dicts: FigureDict,
        *,
        cancel_on_error: bool = False,
        _write: Literal[False],
        stepper: bool = False,
    ) -> bytes: ...

    @overload
    async def write_fig_from_object(
        self,
        fig_dicts: FigureDict | AnyIterable[FigureDict],
        *,
        cancel_on_error: Literal[True],
        _write: Literal[True] = True,
        stepper: bool = False,
    ) -> None: ...

    @overload
    async def write_fig_from_object(
        self,
        fig_dicts: FigureDict | AnyIterable[FigureDict],
        *,
        cancel_on_error: Literal[False] = False,
        _write: Literal[True] = True,
        stepper: bool = False,
    ) -> tuple[Exception]: ...

    @overload
    async def write_fig_from_object(
        self,
        fig_dicts: FigureDict | AnyIterable[FigureDict],
        *,
        cancel_on_error: bool,
        _write: Literal[True] = True,
        stepper: bool = False,
    ) -> tuple[Exception] | None: ...

    async def write_fig_from_object(
        self,
        fig_dicts: FigureDict | AnyIterable[FigureDict],
        *,
        cancel_on_error=False,
        _write: bool = True,  # backwards compatibility!
        stepper: bool = False,
    ) -> None | bytes | tuple[Exception]:
        """
        Create one or more plotly figures from a specification dictionary.

        If every figure needs a different `opts` or `path` argument, you use
        this instead of `write_fig`.

        Args:
            fig_dicts:
                Any single figure dict, or an iterable of figure dictionaries. The
                figure dictionaries *must* have a "fig" key with a plotly figure or
                its dict representation. It can have the following keys: path, opts,
                and topojson. This is roughly equal to the `write_fig` arguments.

            cancel_on_error (boolean, default: False):
                If False, any errors during rendering will be returned from the function
                call in a list. If True, any error will be raised immediately and the
                rest of the renders will be cancelled.

            stepper (boolean, default False):
                This is a debugging argument and is not part of the stable API.
                If set to true, kaleido will wait for a key press to render each
                image, in case one would want to inspect the browser environment.

        Returns:
            If cancel_on_error is True, it always returns None on success.
            If cancel_on_error is False, it always returns a tuple, possibly
            with errors.

        """
        if not _write:
            cancel_on_error = True

        if _is_figuredict(fig_dicts):
            fig_dicts = [fig_dicts]

        name = "No Name"
        if main_task := asyncio.current_task():
            self._main_render_coroutines.add(main_task)
            name = main_task.get_name()

        profiler = _profiler.WriteCall(name)
        self.profiler.append(profiler)

        tasks: set[asyncio.Task] = set()

        try:
            async for fig_arg in _utils.ensure_async_iter(fig_dicts):
                t: asyncio.Task = asyncio.create_task(
                    self._render_task(
                        fig_arg=fig_arg,
                        topojson=fig_arg.get("topojson"),
                        _write=_write,  # backwards compatibility
                        profiler=profiler,
                        stepper=stepper,
                    ),
                )
                tasks.add(t)
                await asyncio.sleep(0)  # this forces the added task to run

            res = await asyncio.gather(*tasks, return_exceptions=not cancel_on_error)
            if not _write:
                return cast("bytes", res[0])
            elif cancel_on_error:
                return None
            else:
                return cast("tuple[Exception]", tuple(r for r in res if r))

        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            if main_task:
                self._main_render_coroutines.remove(main_task)

    async def write_fig(  # noqa: PLR0913
        self,
        fig: fig_tools.Figurish,
        path: None | Path | str = None,
        opts: None | fig_tools.LayoutOpts = None,
        *,
        topojson: str | None = None,
        cancel_on_error: bool = False,
        stepper: bool = False,
    ) -> tuple[Exception] | None:
        """
        Create one or more plotly figures.

        While fig may be an iterable, only a single path and opts may be passed.
        Use write_fig_from_object if you need to specify different paths or opts
        for each figure.

        Args:
            fig:
                A plotly figure or its dict representation. It can have the
                following keys: path, opts, and topojson. This is roughly equal
                to the `write_fig` arguments.

            path (None, Path, str):
                The path where the image will be written. The default is the
                current directory. If a filename isn't specified, we try to
                generate one from the title or use a default "fig-". If you
                pass many figures, this argument should be a directory.

            opts (None, LayoutOpts dict):
                The layout options are a dictionary with the following optional keys:
                - scale: a number to multiply the image by.
                - width: a number to set the pixel width.
                - height: a number to set the pixel height.
                - format: One of jpg, png, svg, pdf, json, or webp.

            topojson:
                An optional json-format map specification when using geomaps.

            cancel_on_error (boolean, default: False):
                If False, any errors during rendering will be returned from the function
                call in a list. If True, any error will be raised immediately and the
                rest of the renders will be cancelled.

            stepper (boolean, default False):
                This is a debugging argument and is not part of the stable API.
                If set to true, kaleido will wait for a key press to render each
                image, in case one would want to inspect the browser environment.

        Returns:
            If cancel_on_error is True, it always returns None on success.
            If cancel_on_error is False, it always returns a tuple, possibly
            with errors.

        """
        if fig_tools.is_figurish(fig) or not isinstance(
            fig,
            (Iterable, AsyncIterable),
        ):
            fig = [fig]

        async def _temp_generator() -> AsyncGenerator[FigureDict, None]:
            async for f in _utils.ensure_async_iter(fig):
                yield {
                    "fig": f,
                    "path": path,
                    "opts": opts,
                    "topojson": topojson,
                }

        generator = cast("AsyncIterable[FigureDict]", _temp_generator())
        return await self.write_fig_from_object(
            fig_dicts=generator,
            cancel_on_error=cancel_on_error,
            stepper=stepper,
        )

    async def calc_fig(
        self,
        fig: fig_tools.Figurish,
        opts: None | fig_tools.LayoutOpts = None,
        *,
        path: None = None,
        topojson: str | None = None,
        stepper: bool = False,
    ) -> bytes:
        """
        Run write_fig but instead of writing a file, return the bytes.

        The arguments are the same as write_fig, but path does nothing.

        Returns:
            The calculated bytes.

        """
        if path is not None:
            warnings.warn(
                "The path argument is deprecated in `kaleido.calc_fig`. "
                "It is ignored and will be removed in a future version",
                DeprecationWarning,
                stacklevel=2,
            )

        spec: FigureDict = {
            "fig": fig,
            "opts": opts,
            "topojson": topojson,
        }
        # pyright > mypy, but:
        # pyright doesn't understand literals in overloads as well
        return await self.write_fig_from_object(  # type: ignore[reportCallIssue]
            fig_dicts=spec,
            cancel_on_error=True,
            _write=False,
            stepper=stepper,
        )
