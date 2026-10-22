import pytest

from kaleido._utils import fig_tools

sources = ["argument", "layout", "template", "default"]
values = [None, 150, 800, 1500]
values2 = [None, 300, 1000, 1300]


@pytest.mark.parametrize("width_source", sources)
@pytest.mark.parametrize("height_source", sources)
@pytest.mark.parametrize("width_value", values)
@pytest.mark.parametrize("height_value", values2)
def test_coerce_for_js_dimensions(
    width_source,
    height_source,
    width_value,
    height_value,
):
    """Test coerce_for_js with all combinations of width/height sources."""

    layout = {}
    opts = {}
    expected_width = width_value

    if width_source == "argument":
        opts["width"] = width_value
    elif width_source == "layout":
        layout["width"] = width_value
    elif width_source == "template":
        layout.setdefault("template", {}).setdefault("layout", {})["width"] = (
            width_value
        )
    else:  # default
        expected_width = None

    # Set to default if None
    if expected_width is None:
        expected_width = fig_tools.DEFAULT_WIDTH

    # Do for height what I did for width
    expected_height = height_value

    if height_source == "argument":
        opts["height"] = height_value
    elif height_source == "layout":
        layout["height"] = height_value
    elif height_source == "template":
        layout.setdefault("template", {}).setdefault("layout", {})["height"] = (
            height_value
        )
    else:  # default
        expected_height = None

    # Set to default if None
    if expected_height is None:
        expected_height = fig_tools.DEFAULT_HEIGHT

    # Create a figure dict with the layout
    fig = {"data": [], "layout": layout}

    # Call the function
    spec = fig_tools.coerce_for_js(fig, None, opts)

    # Assert results
    assert spec["width"] == expected_width, (
        f"Width mismatch: got {spec['width']}, expected {expected_width}, "
        f"source: {width_source}, value: {width_value}"
    )
    assert spec["height"] == expected_height, (
        f"Height mismatch: got {spec['height']}, expected {expected_height}, "
        f"source: {height_source}, value: {height_value}"
    )


@pytest.mark.parametrize("dir_name", ["2024.01.31", "plots.svg"])
def test_coerce_for_js_directory_with_suffix(tmp_path, dir_name):
    """Test coerce_for_js ignores the suffix of a directory path."""
    directory = tmp_path / dir_name
    directory.mkdir()
    fig = {"data": [], "layout": {}}

    spec = fig_tools.coerce_for_js(fig, directory, None)
    assert spec["format"] == fig_tools.DEFAULT_EXT

    spec = fig_tools.coerce_for_js(fig, str(directory), None)
    assert spec["format"] == fig_tools.DEFAULT_EXT
