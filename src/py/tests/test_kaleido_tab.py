import asyncio
from unittest.mock import AsyncMock, Mock

import choreographer
import pytest
from choreographer.errors import DevtoolsProtocolError

from kaleido._kaleido_tab import _KaleidoTab


@pytest.fixture
def tab_events():
    tab = Mock(spec=choreographer.Tab)
    callbacks = {}

    async def emit(event, **params):
        message = {"method": event, "params": params}
        if event in callbacks:
            await callbacks[event](message)

    tab.subscribe.side_effect = callbacks.__setitem__
    tab.unsubscribe.side_effect = lambda event: callbacks.pop(event, None)
    return tab, emit


@pytest.mark.parametrize("load_before_response", [True, False])
@pytest.mark.parametrize(
    ("frame_id", "loader_id", "event_name"),
    [
        ("main", "old-document", "load"),
        ("child", "new-document", "load"),
        ("main", "new-document", "DOMContentLoaded"),
    ],
)
async def test_navigate_waits_for_its_document(
    tab_events,
    load_before_response,
    frame_id,
    loader_id,
    event_name,
):
    tab, emit = tab_events
    enabled = set()
    event_commands = {"Page.enable", "Page.setLifecycleEventsEnabled"}
    navigated_context_id = 2
    navigated = asyncio.Event()

    async def loaded():
        # A fast load must be observed even before Page.navigate returns.
        if event_commands <= enabled:
            await emit("Page.loadEventFired", timestamp=2)
            await emit(
                "Page.lifecycleEvent",
                frameId="main",
                loaderId="new-document",
                name="load",
            )

    async def send_command(command, params=None):  # noqa: ARG001
        if command in event_commands:
            enabled.add(command)
        elif command == "Page.navigate":
            await emit("Page.loadEventFired", timestamp=1)
            if "Page.setLifecycleEventsEnabled" in enabled:
                await emit(
                    "Page.lifecycleEvent",
                    frameId=frame_id,
                    loaderId=loader_id,
                    name=event_name,
                )
            if load_before_response:
                await loaded()
            navigated.set()
            return {"result": {"frameId": "main", "loaderId": "new-document"}}
        elif command == "Runtime.enable":
            await emit(
                "Runtime.executionContextCreated",
                context={
                    "id": navigated_context_id,
                    "auxData": {"frameId": "main", "isDefault": True},
                },
            )
        return {"result": {}}

    tab.send_command = AsyncMock(side_effect=send_command)
    kaleido_tab = _KaleidoTab(tab)
    navigation = asyncio.create_task(kaleido_tab.navigate("file:///index.html"))
    try:
        await asyncio.wait_for(navigated.wait(), timeout=1)
        if not load_before_response:
            assert not navigation.done()
            assert not any(
                call.args[0] == "Runtime.enable"
                for call in tab.send_command.await_args_list
            )
            await loaded()
        await asyncio.wait_for(navigation, timeout=1)
        assert kaleido_tab._current_js_id == navigated_context_id  # noqa: SLF001
        tab.unsubscribe.assert_any_call("Page.lifecycleEvent")
    finally:
        navigation.cancel()
        await asyncio.gather(navigation, return_exceptions=True)


@pytest.mark.parametrize("context_before_response", [True, False])
async def test_navigate_selects_main_frame_default_context(
    tab_events, context_before_response
):
    tab, emit = tab_events
    runtime_enabled = asyncio.Event()
    navigated_context_id = 4

    async def context_ready():
        await emit(
            "Runtime.executionContextCreated",
            context={
                "id": navigated_context_id,
                "auxData": {"frameId": "main", "isDefault": True},
            },
        )

    async def send_command(command, params=None):  # noqa: ARG001
        if command == "Page.navigate":
            await emit(
                "Page.lifecycleEvent",
                frameId="main",
                loaderId="new-document",
                name="load",
            )
            return {"result": {"frameId": "main", "loaderId": "new-document"}}
        if command == "Runtime.enable":
            for context in (
                {"id": 1, "auxData": {"frameId": "child", "isDefault": True}},
                {"id": 2, "auxData": {"frameId": "main", "isDefault": False}},
                {"id": 3},
            ):
                await emit("Runtime.executionContextCreated", context=context)
            if context_before_response:
                await context_ready()
            runtime_enabled.set()
        return {"result": {}}

    tab.send_command = AsyncMock(side_effect=send_command)
    kaleido_tab = _KaleidoTab(tab)
    navigation = asyncio.create_task(kaleido_tab.navigate("file:///index.html"))
    try:
        await asyncio.wait_for(runtime_enabled.wait(), timeout=1)
        if not context_before_response:
            assert not navigation.done()
            await context_ready()
        await asyncio.wait_for(navigation, timeout=1)
        assert kaleido_tab._current_js_id == navigated_context_id  # noqa: SLF001
        tab.unsubscribe.assert_any_call("Runtime.executionContextCreated")
    finally:
        navigation.cancel()
        await asyncio.gather(navigation, return_exceptions=True)


@pytest.mark.parametrize(
    ("failed_command", "response", "error", "message"),
    [
        (
            "Page.navigate",
            {"result": {"errorText": "net::ERR_FILE_NOT_FOUND"}},
            RuntimeError,
            "net::ERR_FILE_NOT_FOUND",
        ),
        (
            "Page.navigate",
            {"error": {"code": -32000, "message": "Navigation failed"}},
            DevtoolsProtocolError,
            "Navigation failed",
        ),
        (
            "Runtime.enable",
            {"error": {"code": -32000, "message": "Runtime unavailable"}},
            DevtoolsProtocolError,
            "Runtime unavailable",
        ),
    ],
)
async def test_navigate_cleans_up_after_failure(
    tab_events, failed_command, response, error, message
):
    tab, emit = tab_events

    async def send_command(command, params=None):  # noqa: ARG001
        if command == failed_command:
            return response
        if command == "Page.navigate":
            await emit(
                "Page.lifecycleEvent",
                frameId="main",
                loaderId="new-document",
                name="load",
            )
            return {"result": {"frameId": "main", "loaderId": "new-document"}}
        return {"result": {}}

    tab.send_command = AsyncMock(side_effect=send_command)
    with pytest.raises(error, match=message):
        await asyncio.wait_for(
            _KaleidoTab(tab).navigate("file:///missing.html"), timeout=1
        )
    tab.unsubscribe.assert_any_call("Page.lifecycleEvent")
    if failed_command == "Runtime.enable":
        tab.unsubscribe.assert_any_call("Runtime.executionContextCreated")


@pytest.mark.parametrize("waiting_for_context", [True, False])
async def test_navigate_cleans_up_after_cancellation(tab_events, waiting_for_context):
    tab, emit = tab_events
    ready_to_cancel = asyncio.Event()

    async def send_command(command, params=None):  # noqa: ARG001
        if command == "Page.navigate":
            if waiting_for_context:
                await emit(
                    "Page.lifecycleEvent",
                    frameId="main",
                    loaderId="new-document",
                    name="load",
                )
            else:
                ready_to_cancel.set()
            return {"result": {"frameId": "main", "loaderId": "new-document"}}
        if command == "Runtime.enable":
            ready_to_cancel.set()
        return {"result": {}}

    tab.send_command = AsyncMock(side_effect=send_command)
    navigation = asyncio.create_task(_KaleidoTab(tab).navigate("file:///index.html"))
    try:
        await asyncio.wait_for(ready_to_cancel.wait(), timeout=1)
    finally:
        navigation.cancel()
        await asyncio.gather(navigation, return_exceptions=True)
    assert navigation.cancelled()
    tab.unsubscribe.assert_any_call("Page.lifecycleEvent")
    if waiting_for_context:
        tab.unsubscribe.assert_any_call("Runtime.executionContextCreated")
