"""
Tools to help prepare data for plotly.js from kaleido.

It 1. validates, 2. write defaults, 3. packages object.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, TypedDict

import logistro

from . import font_tools, path_tools

if TYPE_CHECKING:
    from pathlib import Path
    from typing import Any

    from typing_extensions import NotRequired, TypeGuard

    Figurish = Any  # Be nice to make it more specific, dictionary or something
    FormatString = Literal["png", "jpg", "jpeg", "webp", "svg", "json", "pdf"]


# Input of to_spec (user gives us this)
class LayoutOpts(TypedDict, total=False):
    format: FormatString | None
    scale: int | float
    height: int | float
    width: int | float
    # Paths to font files (.ttf/.otf/.woff) to embed into vector output so the
    # figure renders with them without the fonts being installed system-wide.
    fonts: list[str | Path]


# Output of to_spec (we give kaleido_scopes.js this)
# refactor note: this could easily be right before send
class Spec(TypedDict):
    format: FormatString
    width: int | float
    height: int | float
    scale: int | float
    data: Figurish
    fonts: NotRequired[list[font_tools.FontFace]]


_logger = logistro.getLogger(__name__)

# constants
DEFAULT_EXT = "png"
DEFAULT_SCALE = 1
DEFAULT_WIDTH = 700
DEFAULT_HEIGHT = 500
SUPPORTED_FORMATS: tuple[FormatString, ...] = (
    "png",
    "jpg",
    "jpeg",
    "webp",
    "svg",
    "json",
    "pdf",
)


def is_figurish(o: Any) -> TypeGuard[Figurish]:
    """Detect if input is a plotly figure or equivalent."""
    # so if data isn't in the dict things get weird.
    valid = hasattr(o, "to_dict") or (isinstance(o, dict) and "data" in o)
    if not valid:
        _logger.debug(
            f"Figure has to_dict? {hasattr(o, 'to_dict')} "
            f"is dict? {isinstance(o, dict)} "
            f"Keys: {o.keys() if hasattr(o, 'keys') else None!s}",
        )
    return valid


def _coerce_format(extension: str) -> FormatString:
    """Satisfies a type checker that our format string is an accepted format."""

    def is_fmt(s: str) -> TypeGuard[FormatString]:
        return s in SUPPORTED_FORMATS

    formatted_extension = extension.lower()
    if formatted_extension == "jpg":
        return "jpeg"
    elif not is_fmt(formatted_extension):
        raise ValueError(
            f"Invalid format '{formatted_extension}'.\n"
            f"Supported formats: {SUPPORTED_FORMATS!s}",
        )
    else:
        return formatted_extension


def coerce_for_js(
    fig: Figurish,
    path: Path | str | None,
    opts: LayoutOpts | None,
) -> Spec:
    """
    Package fig, path, and opts into a dictionary that javascript understands.

    This will
        - validate the inputs
        - coerce the inputs if needed (eg. jpeg --> jpg)
        - provide defaults if we can
    """
    if not is_figurish(fig):  # VALIDATE FIG
        raise TypeError("Figure supplied doesn't seem to be a valid plotly figure.")
    if hasattr(fig, "to_dict"):  # COERCE FIG
        fig = fig.to_dict()

    path = path_tools.get_path(path) if path else None

    opts = opts or {}

    if _rest := opts - LayoutOpts.__annotations__.keys():
        raise AttributeError(f"Unknown key(s) in layout options: {_rest}")

    # Extract info
    file_format = _coerce_format(
        opts.get("format")
        or (path.suffix.lstrip(".") if path and path.suffix else DEFAULT_EXT),
    )

    layout = fig.get("layout", {})

    width = (
        opts.get("width")
        or layout.get("width")
        or layout.get("template", {}).get("layout", {}).get("width")
        or DEFAULT_WIDTH
    )

    height = (
        opts.get("height")
        or layout.get("height")
        or layout.get("template", {}).get("layout", {}).get("height")
        or DEFAULT_HEIGHT
    )

    scale = opts.get("scale", DEFAULT_SCALE)

    # PACKAGING
    spec: Spec = {
        "format": file_format,
        "width": width,
        "height": height,
        "scale": scale,
        "data": fig,
    }

    # Custom fonts: read each file once, derive its family name, and package it
    # as a base64 @font-face descriptor for the render scope to embed.
    if fonts := opts.get("fonts"):
        spec["fonts"] = [font_tools.font_face_from_path(font) for font in fonts]

    return spec
