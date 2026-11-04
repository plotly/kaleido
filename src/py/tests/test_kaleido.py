from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest
from choreographer.browsers import chromium
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from kaleido import Kaleido
from kaleido.errors import ChromeNotFoundError

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Generator

    from kaleido import FigureDict


# can't do session scope because pytest complains that its used by
# function-scoped loops. tried to create a separate loop in here with
# session, lots of spooky errors, even asyncio.run() doesn't clean up right.
@pytest.fixture(scope="function")
async def simple_figure_with_bytes():
    """Create a simple figure with calculated bytes and PNG assertion."""
    import plotly.express as px  # type: ignore[import-untyped] # noqa: PLC0415

    fig = px.line(x=[1, 2, 3], y=[1, 2, 3])

    async with Kaleido() as k:
        bytes_data = await k.calc_fig(
            fig,
            opts={"format": "png", "width": 400, "height": 300},
        )

    # Assert it's a PNG by checking the PNG signature
    assert bytes_data[:8] == b"\x89PNG\r\n\x1a\n", "Generated data is not a valid PNG"

    return {
        "fig": fig,
        "bytes": bytes_data,
        "opts": {"format": "png", "width": 400, "height": 300},
    }


async def test_write_fig_from_object_sync_generator(simple_figure_with_bytes, tmp_path):
    """Test write_fig_from_object with sync generator."""

    file_paths = []

    def fig_generator() -> Generator[FigureDict, None]:
        for i in range(2):
            path = tmp_path / f"test_sync_{i}.png"
            file_paths.append(path)
            yield {
                "fig": simple_figure_with_bytes["fig"],
                "path": path,
                "opts": simple_figure_with_bytes["opts"],
            }

    async with Kaleido() as k:
        await k.write_fig_from_object(fig_generator())

    # Assert that each created file matches the fixture bytes
    for path in file_paths:
        assert path.exists(), f"File {path} was not created"
        created_bytes = path.read_bytes()
        assert created_bytes == simple_figure_with_bytes["bytes"], (
            f"File {path} bytes don't match fixture bytes"
        )


async def test_write_fig_from_object_async_generator(
    simple_figure_with_bytes,
    tmp_path,
):
    """Test write_fig_from_object with async generator."""

    file_paths = []

    async def fig_async_generator() -> AsyncGenerator[FigureDict, None]:
        for i in range(2):
            path = tmp_path / f"test_async_{i}.png"
            file_paths.append(path)
            yield {
                "fig": simple_figure_with_bytes["fig"],
                "path": path,
                "opts": simple_figure_with_bytes["opts"],
            }

    async with Kaleido() as k:
        await k.write_fig_from_object(fig_async_generator())

    # Assert that each created file matches the fixture bytes
    for path in file_paths:
        assert path.exists(), f"File {path} was not created"
        created_bytes = path.read_bytes()
        assert created_bytes == simple_figure_with_bytes["bytes"], (
            f"File {path} bytes don't match fixture bytes"
        )


async def test_write_fig_from_object_iterator(simple_figure_with_bytes, tmp_path):
    """Test write_fig_from_object with iterator."""

    fig_list = []
    file_paths = []
    for i in range(2):
        path = tmp_path / f"test_iter_{i}.png"
        file_paths.append(path)
        fig_list.append(
            {
                "fig": simple_figure_with_bytes["fig"],
                "path": path,
                "opts": simple_figure_with_bytes["opts"],
            },
        )

    async with Kaleido() as k:
        await k.write_fig_from_object(fig_list)

    # Assert that each created file matches the fixture bytes
    for path in file_paths:
        assert path.exists(), f"File {path} was not created"
        created_bytes = path.read_bytes()
        assert created_bytes == simple_figure_with_bytes["bytes"], (
            f"File {path} bytes don't match fixture bytes"
        )


async def test_write_fig_from_object_return_modes(simple_figure_with_bytes, tmp_path):
    """Test write_fig_from_object with different return schemes."""

    fig_list = []
    file_paths = []
    for i in range(2):
        path = tmp_path / "does_not_exist" / f"test_iter_{i}.png"
        file_paths.append(path)
        fig_list.append(
            {
                "fig": simple_figure_with_bytes["fig"],
                "path": path,
                "opts": simple_figure_with_bytes["opts"],
            },
        )

    # test collecting errors
    async with Kaleido() as k:
        res = await k.write_fig_from_object(fig_list, cancel_on_error=False)
    for r in res:
        assert isinstance(r, RuntimeError)
    assert len(res) == len(fig_list)

    # test not collecting errors
    with pytest.raises(RuntimeError):
        async with Kaleido() as k:
            res = await k.write_fig_from_object(fig_list, cancel_on_error=True)

    # test returning
    async with Kaleido() as k:
        res = await k.write_fig_from_object(fig_list[0], _write=False)
    assert res == simple_figure_with_bytes["bytes"]

    # Assert that each created file matches the fixture bytes
    for path in file_paths:
        assert not path.exists()


async def test_write_fig_from_object_bare_dictionary(
    simple_figure_with_bytes,
    tmp_path,
):
    """Test write_fig_from_object with bare dictionary."""

    path1 = tmp_path / "test_dict_1.png"

    fig_data: FigureDict = {
        "fig": simple_figure_with_bytes["fig"],
        "path": path1,
        "opts": simple_figure_with_bytes["opts"],
    }

    async with Kaleido() as k:
        await k.write_fig_from_object(fig_data)

    # Assert that each created file matches the fixture bytes
    assert path1.exists(), f"File {path1} was not created"
    created_bytes = path1.read_bytes()
    assert created_bytes == simple_figure_with_bytes["bytes"], (
        f"File {path1} bytes don't match fixture bytes"
    )


@pytest.fixture(scope="function")
def test_kaleido():  # speed up hypothesis test using a function fixture
    return Kaleido()


@settings(
    suppress_health_check=[HealthCheck.function_scoped_fixture],
    max_examples=50,
)
@given(
    path=st.text(
        min_size=1,
        max_size=50,
        alphabet=st.characters(whitelist_categories=["L", "N"]),
    ),
    width=st.integers(min_value=100, max_value=2000),
    height=st.integers(min_value=100, max_value=2000),
    format_type=st.sampled_from(["png", "svg", "pdf", "html"]),
    topojson=st.one_of(st.none(), st.text(min_size=1, max_size=20)),
)
@pytest.mark.parametrize(
    "cancel_on_error",
    [
        True,
        False,
    ],
    ids=("cancel_on_error", "collect_errors"),
)
async def test_write_fig_argument_passthrough(  #  noqa: PLR0913
    test_kaleido,
    cancel_on_error,
    tmp_path,
    path,
    width,
    height,
    format_type,
    topojson,
):
    test_path = tmp_path / f"{path}.{format_type}"
    opts = {"format": format_type, "width": width, "height": height}
    fig = {"data": "test"}
    # Mock write_fig_from_object to capture arguments
    with patch.object(
        Kaleido,
        "write_fig_from_object",
        new=AsyncMock(return_value=[]),
    ) as mock_write_fig_from_object:
        await test_kaleido.write_fig(
            fig,
            path=test_path,
            opts=opts,
            topojson=topojson,
            cancel_on_error=cancel_on_error,
        )
        # Verify write_fig_from_object was called
        mock_write_fig_from_object.assert_called_once()

        # Extract the generator that was passed as first argument
        _, kwargs = mock_write_fig_from_object.call_args  # not sure.

        generator = kwargs["fig_dicts"]
        assert kwargs["cancel_on_error"] == cancel_on_error

        # Convert generator to list to inspect its contents
        generated_args_list = [v async for v in generator]
        assert len(generated_args_list) == 1, (
            "Expected generator to yield exactly one item"
        )

        generated_args = generated_args_list[0]

        # Validate that the generated arguments match what we passed to write_fig
        assert "fig" in generated_args, "Generated args should contain 'fig'"
        assert "path" in generated_args, "Generated args should contain 'path'"
        assert "opts" in generated_args, "Generated args should contain 'opts'"
        assert "topojson" in generated_args, "Generated args should contain 'topojson'"

        # Check that the values match
        assert generated_args["fig"] == fig, "Figure should match"
        assert str(generated_args["path"]) == str(test_path), "Path should match"
        assert generated_args["opts"] == opts, "Options should match"
        assert generated_args["topojson"] == topojson, "Topojson should match"


@settings(
    suppress_health_check=[HealthCheck.function_scoped_fixture],
    max_examples=50,
)
@given(
    width=st.integers(min_value=100, max_value=2000),
    height=st.integers(min_value=100, max_value=2000),
    format_type=st.sampled_from(["png", "svg", "pdf", "html"]),
    topojson=st.one_of(st.none(), st.text(min_size=1, max_size=20)),
)
async def test_calc_fig_argument_passthrough(
    test_kaleido,
    width,
    height,
    format_type,
    topojson,
):
    opts = {"format": format_type, "width": width, "height": height}
    fig = {"data": "test"}
    # Mock write_fig_from_object to capture arguments
    with patch.object(
        Kaleido,
        "write_fig_from_object",
        new=AsyncMock(return_value=[]),
    ) as mock_write_fig_from_object:
        await test_kaleido.calc_fig(
            fig,
            opts=opts,
            topojson=topojson,
        )
        # Verify write_fig_from_object was called
        mock_write_fig_from_object.assert_called_once()

        # Extract the generator that was passed as first argument
        _, kwargs = mock_write_fig_from_object.call_args  # not sure.

        fig_dict = kwargs["fig_dicts"]
        assert kwargs["cancel_on_error"] is True
        assert kwargs["_write"] is False

        # Validate that the generated arguments match what we passed to write_fig
        assert "fig" in fig_dict, "Generated args should contain 'fig'"
        assert "opts" in fig_dict, "Generated args should contain 'opts'"
        assert "topojson" in fig_dict, "Generated args should contain 'topojson'"

        # Check that the values match
        assert fig_dict["fig"] == fig, "Figure should match"
        assert fig_dict["opts"] == opts, "Options should match"
        assert fig_dict["topojson"] == topojson, "Topojson should match"


async def test_kaleido_instantiate_no_hang():
    """Test that instantiating Kaleido doesn't hang."""
    _ = Kaleido()


async def test_kaleido_instantiate_and_close():
    """Test that instantiating and closing Kaleido works."""
    # Maybe there should be a warning or error when closing without opening?
    k = Kaleido()
    await k.close()


async def test_kaleido_reports_bad_path():
    """Test that a browser path passed by the user is named in the error."""
    with pytest.raises(ChromeNotFoundError, match="path='/nonexistent/chrome'"):
        Kaleido(path="/nonexistent/chrome")


async def test_kaleido_reports_bad_browser_path_env(monkeypatch):
    """Test that a BROWSER_PATH set by the user is named in the error."""
    monkeypatch.setenv("BROWSER_PATH", "/nonexistent/chrome")
    # a downloaded chrome takes precedence over BROWSER_PATH, so hide it
    monkeypatch.setattr(chromium, "get_chrome_download_path", lambda **_: None)
    monkeypatch.setattr(chromium, "get_old_chrome_download_path", lambda: None)
    with pytest.raises(ChromeNotFoundError, match="BROWSER_PATH='/nonexistent/chrome'"):
        Kaleido()


async def test_all_methods_context(simple_figure_with_bytes, tmp_path):
    """Test write, write_from_object, and calc with context."""
    fig = simple_figure_with_bytes["fig"]
    opts = simple_figure_with_bytes["opts"]
    expected_bytes = simple_figure_with_bytes["bytes"]

    # Test with context manager
    async with Kaleido() as k:
        # Test calc_fig
        calc_bytes = await k.calc_fig(fig, opts=opts)
        assert calc_bytes == expected_bytes, "calc_fig bytes don't match fixture"

        # Test write_fig
        write_path = tmp_path / "context_write.png"
        await k.write_fig(fig, path=write_path, opts=opts)
        assert write_path.exists(), "write_fig didn't create file"
        write_bytes = write_path.read_bytes()
        assert write_bytes == expected_bytes, "write_fig bytes don't match fixture"

        # Test write_fig_from_object
        obj_path = tmp_path / "context_obj.png"
        await k.write_fig_from_object([{"fig": fig, "path": obj_path, "opts": opts}])
        assert obj_path.exists(), "write_fig_from_object didn't create file"
        obj_bytes = obj_path.read_bytes()
        assert obj_bytes == expected_bytes, (
            "write_fig_from_object bytes don't match fixture"
        )


async def test_all_methods_non_context(simple_figure_with_bytes, tmp_path):
    """Test write, write_from_object, and calc with non-context."""
    fig = simple_figure_with_bytes["fig"]
    opts = simple_figure_with_bytes["opts"]
    expected_bytes = simple_figure_with_bytes["bytes"]

    # Test without context manager
    k: Kaleido = Kaleido()
    await k  # could do it on one line but it tricks typer
    try:
        # Test calc_fig
        calc_bytes = await k.calc_fig(fig, opts=opts)
        assert calc_bytes == expected_bytes, (
            "Non-context calc_fig bytes don't match fixture"
        )

        # Test write_fig

        write_path2 = tmp_path / "non_context_write.png"
        await k.write_fig(fig, path=write_path2, opts=opts)

        assert write_path2.exists(), "Non-context write_fig didn't create file"
        write_bytes2 = write_path2.read_bytes()
        assert write_bytes2 == expected_bytes, (
            "Non-context write_fig bytes don't match fixture"
        )

        obj_path2 = tmp_path / "non_context_obj.png"
        await k.write_fig_from_object([{"fig": fig, "path": obj_path2, "opts": opts}])
        assert obj_path2.exists(), (
            "Non-context write_fig_from_object didn't create file"
        )
        obj_bytes2 = obj_path2.read_bytes()
        assert obj_bytes2 == expected_bytes, (
            "Non-context write_fig_from_object bytes don't match fixture"
        )

    finally:
        await k.close()


@pytest.mark.parametrize("n_tabs", [1, 2, 3])
async def test_tab_count_verification(n_tabs):
    """Test that Kaleido creates the correct number of tabs."""
    async with Kaleido(n=n_tabs) as k:
        # Check the queue size matches expected tabs
        assert k.tabs_ready.qsize() == n_tabs, (
            f"Queue size {k.tabs_ready.qsize()} != {n_tabs}"
        )

        # Use devtools protocol to verify tab count
        # Send getTargets command directly to Kaleido (which is a Browser/Target)
        result = await k.send_command("Target.getTargets")
        # Count targets that are pages (not service workers, etc.)
        page_targets = [
            t for t in result["result"]["targetInfos"] if t.get("type") == "page"
        ]
        assert len(page_targets) >= n_tabs, (
            f"Found {len(page_targets)} page targets, expected at least {n_tabs}"
        )


async def test_unreasonable_timeout(simple_figure_with_bytes, tmp_path):
    """Test that an unreasonably small timeout actually times out."""

    fig = simple_figure_with_bytes["fig"]
    opts = simple_figure_with_bytes["opts"]

    async def fig_generator() -> AsyncGenerator[FigureDict, None]:
        yield {
            "fig": fig,
            "path": tmp_path / "test_timeout.png",
            "opts": opts,
        }

    async with Kaleido(timeout=0.1) as k:

        async def slow_calc_fig(*_args, **_kwargs):
            """Wrapper that adds sleep then fails."""
            await asyncio.sleep(1)
            pytest.fail("Should have timed out before reaching here!")

        for _ in range(k.tabs_ready.qsize()):
            t = await k.tabs_ready.get()
            t._calc_fig = slow_calc_fig  # noqa: SLF001
            await k.tabs_ready.put(t)

        with pytest.raises((asyncio.TimeoutError, TimeoutError)):  # noqa: PT012
            await k.write_fig_from_object(fig_generator(), cancel_on_error=True)
            pytest.fail("Should never reach this, should have raised.")

    ret = await k.write_fig_from_object(fig_generator(), cancel_on_error=False)
    assert isinstance(ret[0], (asyncio.TimeoutError, TimeoutError))


async def test_env_timeout_override(monkeypatch, simple_figure_with_bytes):
    """Test that env timeout is used when set to valid value."""
    monkeypatch.setenv("KALEIDO_RENDER_TIMEOUT", "0.1")

    fig = simple_figure_with_bytes["fig"]
    opts = simple_figure_with_bytes["opts"]

    async with Kaleido(timeout="auto") as k:

        async def slow_calc_fig(*_args, **_kwargs):
            await asyncio.sleep(1)
            pytest.fail("Should have timed out before reaching here!")

        for _ in range(k.tabs_ready.qsize()):
            t = await k.tabs_ready.get()
            t._calc_fig = slow_calc_fig  # noqa: SLF001
            await k.tabs_ready.put(t)

        with pytest.raises((asyncio.TimeoutError, TimeoutError)):  # noqa: PT012
            await k.write_fig(fig, opts=opts, cancel_on_error=True)


@pytest.mark.parametrize(
    ("plotlyjs", "mathjax"),
    [
        ("https://cdn.plot.ly/plotly-latest.min.js", None),
        (
            None,
            "https://cdnjs.cloudflare.com/ajax/libs/mathjax/3.2.0/es5/tex-chtml.min.js",
        ),
        (
            "https://cdn.plot.ly/plotly-latest.min.js",
            "https://cdnjs.cloudflare.com/ajax/libs/mathjax/3.2.0/es5/tex-chtml.min.js",
        ),
    ],
)  # THESE STRINGS DON'T ACTUALLY MATTER!
async def test_plotlyjs_mathjax_injection(plotlyjs, mathjax):
    """Test that plotlyjs and mathjax URLs are properly injected."""

    async with Kaleido(plotlyjs=plotlyjs, mathjax=mathjax) as k:
        # Get a tab from the public queue to check the page source
        tab = await k.tabs_ready.get()
        try:
            # Get the page source using devtools protocol
            result = await tab.tab.send_command(
                "Runtime.evaluate",
                {
                    "expression": "document.documentElement.outerHTML",
                },
            )
            source = result["result"]["result"]["value"]

            if plotlyjs:
                # Check if plotlyjs URL is in the source
                plotly_pattern = re.escape(plotlyjs)
                assert re.search(plotly_pattern, source), (
                    f"Plotlyjs URL {plotlyjs} not found in page source"
                )

            if mathjax:
                # Check if mathjax URL is in the source
                mathjax_pattern = re.escape(mathjax)
                assert re.search(mathjax_pattern, source), (
                    f"Mathjax URL {mathjax} not found in page source"
                )

        finally:
            # Put the tab back in the queue
            await k.tabs_ready.put(tab)


async def test_headers_stored_on_tabs():
    """Test that custom headers are passed through to _KaleidoTab instances."""
    test_headers = {"Referer": "https://example.com/", "X-Custom": "value"}

    async with Kaleido(headers=test_headers, n=1) as k:
        tab = await k.tabs_ready.get()
        try:
            assert tab._headers == test_headers  # noqa: SLF001
        finally:
            await k.tabs_ready.put(tab)


async def test_headers_none_by_default():
    """Test that headers default to None when not specified."""
    async with Kaleido(n=1) as k:
        tab = await k.tabs_ready.get()
        try:
            assert tab._headers is None  # noqa: SLF001
        finally:
            await k.tabs_ready.put(tab)


async def test_headers_rendering_works(simple_figure_with_bytes):
    """Test that rendering still works correctly when headers are set."""
    test_headers = {"Referer": "https://example.com/"}

    async with Kaleido(headers=test_headers) as k:
        result = await k.calc_fig(
            simple_figure_with_bytes["fig"],
            opts=simple_figure_with_bytes["opts"],
        )

    assert result[:8] == b"\x89PNG\r\n\x1a\n", "Generated data is not a valid PNG"
