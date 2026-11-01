import asyncio
from unittest.mock import AsyncMock, Mock

import choreographer

from kaleido._kaleido_tab import _KaleidoTab


async def test_navigate_when_page_loads_before_navigation_returns():
    tab = Mock(spec=choreographer.Tab)
    javascript_ready = asyncio.get_running_loop().create_future()
    page_ready = asyncio.get_running_loop().create_future()
    tab.subscribe_once.side_effect = {
        "Runtime.executionContextCreated": javascript_ready,
        "Page.loadEventFired": page_ready,
    }.__getitem__
    page_enabled = False
    navigated_context_id = 2
    context_id = 1

    async def send_command(command, params=None):  # noqa: ARG001
        nonlocal page_enabled, context_id
        if command == "Page.enable":
            page_enabled = True
        elif command == "Page.navigate":
            context_id = navigated_context_id
            # Chrome does not replay a load event missed while Page was disabled.
            if page_enabled:
                page_ready.set_result({})
        elif command == "Runtime.enable":
            javascript_ready.set_result({"params": {"context": {"id": context_id}}})
        return {"result": {}}

    tab.send_command = AsyncMock(side_effect=send_command)
    kaleido_tab = _KaleidoTab(tab)

    await asyncio.wait_for(kaleido_tab.navigate("file:///index.html"), timeout=1)

    assert kaleido_tab._current_js_id == navigated_context_id  # noqa: SLF001
