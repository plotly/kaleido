from __future__ import annotations

import asyncio
import base64
from typing import TYPE_CHECKING

import logistro

from . import _devtools_utils as _dtools
from . import _js_logger
from ._errors import _raise_error

if TYPE_CHECKING:
    from pathlib import Path

    import choreographer as choreo

    from kaleido._utils import fig_tools


_TEXT_FORMATS = ("svg", "json")  # eps

_logger = logistro.getLogger(__name__)


def _subscribe_new(tab: choreo.Tab, event: str) -> asyncio.Future:
    """Create subscription to tab clearing old ones first: helper function."""
    new_future = tab.subscribe_once(event)
    while new_future.done():
        _logger.debug2(f"Clearing an old {event}")
        new_future = tab.subscribe_once(event)
    return new_future


class _KaleidoTab:
    """
    A Kaleido tab is a wrapped choreographer tab providing the functions we need.

    The choreographer tab can be accessed through the `self.tab` attribute.
    """

    tab: choreo.Tab
    """The underlying choreographer tab."""
    js_logger: _js_logger.JavascriptLogger
    """A log for recording javascript."""

    def __init__(self, tab, *, headers: dict[str, str] | None = None):
        """
        Create a new _KaleidoTab.

        Args:
            tab: the choreographer tab to wrap.

            headers (dict[str, str] | None, optional):
                Extra HTTP headers to send with every request made by the
                browser tab. Defaults to None.

        """
        self.tab = tab
        self._headers = headers
        self.js_logger = _js_logger.JavascriptLogger(self.tab)

    async def navigate(self, url: str | Path = ""):
        """
        Navigate to the kaleidofier script. This is effectively the real initialization.

        Args:
            url: Override the location of the kaleidofier script if necessary.

        """
        # Subscribe to event indicating that page or a subframe has loaded. We queue
        # these events and filter them afterwards once we know the IDs from our
        # navigation. We can't simply wait for the first load event, because it could
        # come from Chrome's new tab page.
        load_events: asyncio.Queue[dict] = asyncio.Queue()

        async def on_lifecycle(event):
            if event["params"]["name"] == "load":
                load_events.put_nowait(event["params"])

        self.tab.subscribe("Page.lifecycleEvent", on_lifecycle)

        try:
            await self._apply_headers()

            # Enable events before navigating so fast loads cannot be missed.
            _logger.debug2(f"Calling Page.enable on {self.tab}")
            _raise_error(await self.tab.send_command("Page.enable"))
            _raise_error(
                await self.tab.send_command(
                    "Page.setLifecycleEventsEnabled",
                    params={"enabled": True},
                ),
            )

            # Navigating page. This will trigger the above events.
            _logger.debug2(f"Calling Page.navigate on {self.tab}")
            _raise_error(
                navigate_response := await self.tab.send_command(
                    "Page.navigate", params={"url": url}
                )
            )
            navigation = navigate_response["result"]
            if error := navigation.get("errorText"):
                raise RuntimeError(f"Navigation to {url} failed: {error}")

            # Wait for the correct load event which matches the navigation we made.
            while True:
                loaded = await load_events.get()
                if (
                    loaded["frameId"] == navigation["frameId"]
                    and loaded["loaderId"] == navigation["loaderId"]
                ):
                    break
        finally:
            self.tab.unsubscribe("Page.lifecycleEvent")

        # Runtime.enable reports existing contexts; wait for load to avoid old ones.
        contexts: asyncio.Queue[int] = asyncio.Queue()

        async def on_context_created(event):
            context = event["params"]["context"]
            aux = context.get("auxData", {})
            if (
                aux.get("frameId") == navigation["frameId"]
                and aux.get("isDefault") is True
            ):
                contexts.put_nowait(context["id"])

        self.tab.subscribe("Runtime.executionContextCreated", on_context_created)
        try:
            _logger.debug2(f"Calling Runtime.enable on {self.tab}")
            _raise_error(await self.tab.send_command("Runtime.enable"))
            self._current_js_id = await contexts.get()
        finally:
            self.tab.unsubscribe("Runtime.executionContextCreated")

        # this runs *after* page load because running it first thing
        # requires a couple extra lines
        self.js_logger.reset()

    # reload is truly so close to navigate
    async def reload(self):
        """Reload the tab, and set the javascript runtime id."""
        _logger.debug(f"Reloading tab {self.tab} with javascript.")

        javascript_ready = _subscribe_new(self.tab, "Runtime.executionContextCreated")

        page_ready = _subscribe_new(self.tab, "Page.loadEventFired")

        _logger.debug2(f"Calling Page.reload on {self.tab}")
        _raise_error(await self.tab.send_command("Page.reload"))

        self._current_js_id = _dtools.get_js_id(await javascript_ready)

        await page_ready

        self.js_logger.reset()

    async def _apply_headers(self):
        """Apply extra HTTP headers to the tab if configured."""
        if self._headers:
            _logger.debug(f"Setting extra HTTP headers on {self.tab}")
            _logger.debug2(f"Extra headers are: {self._headers}")
            _raise_error(await self.tab.send_command("Network.enable"))
            _raise_error(
                await self.tab.send_command(
                    "Network.setExtraHTTPHeaders",
                    params={"headers": self._headers},
                )
            )

    async def _calc_fig(
        self,
        spec: fig_tools.Spec,
        *,
        topojson: str | None,
        render_prof,
        stepper,
    ) -> bytes:
        # Choreographer serializes the spec with the registered PlotlyJSONEncoder
        # and splits messages that exceed the Chrome devtools buffer
        kaleido_js_fn = (
            r"function(spec, ...args)"
            r"{"
            r"return kaleido_scopes.plotly(spec, ...args).then(JSON.stringify);"
            r"}"
        )
        render_prof.profile_log.tick("sending javascript")
        result = await _dtools.exec_js_fn(
            self.tab,
            self._current_js_id,
            kaleido_js_fn,
            spec,
            topojson,
            stepper,
        )
        _raise_error(result)
        render_prof.profile_log.tick("javascript sent")

        _logger.debug2(f"Result of function call: {result}")
        js_response = _dtools.check_kaleido_js_response(result)

        if (response_format := js_response.get("format")) == "pdf":
            render_prof.profile_log.tick("printing pdf")
            img_raw = await _dtools.print_pdf(self.tab)
            render_prof.profile_log.tick("pdf printed")
        else:
            img_raw = js_response["result"]

        if response_format not in _TEXT_FORMATS:
            res = base64.b64decode(img_raw)
        else:
            res = str.encode(img_raw)

        render_prof.data_out_size = len(res)
        render_prof.js_log = self.js_logger.log
        return res
