"""
Tools for embedding custom fonts into vector exports.

Plotly's SVG output only references fonts by name; it never embeds the font
itself. When Kaleido renders that SVG (for PDF, SVG, or EPS), the font name is
resolved against fonts available to the browser/OS, so a font that is not
installed falls back to a default (e.g. Times New Roman).

This module turns a font file on disk into a self-describing ``@font-face``
descriptor (family name + format hint + base64 ``data:`` URL). The descriptor
is sent to the render scope, which both loads the font in the page (so text is
measured correctly) and embeds it into the produced SVG (so the vector output
is self-contained and needs no system font installation).

The font family name is read directly from the font's ``name`` table, so the
caller only has to supply the file path; the family they reference in the
figure's ``font_family`` is matched automatically.

Only the uncompressed sfnt formats (``.ttf``/``.otf``) and ``.woff`` are
parsed. ``.woff2`` stores all tables in a single Brotli stream and cannot be
read without a Brotli decoder, so it is rejected with an actionable error.
"""

from __future__ import annotations

import base64
import struct
import zlib
from pathlib import Path
from typing import TYPE_CHECKING

import logistro

if TYPE_CHECKING:
    from typing import TypedDict

    class FontFace(TypedDict):
        family: str
        format: str
        url: str


_logger = logistro.getLogger(__name__)

# sfnt flavor (first 4 bytes) -> (@font-face format hint, data: URL mime type)
_SFNT_FLAVORS = {
    b"\x00\x01\x00\x00": ("truetype", "font/ttf"),  # TrueType outlines
    b"true": ("truetype", "font/ttf"),  # legacy Apple TrueType
    b"typ1": ("truetype", "font/ttf"),  # legacy Apple Type 1
    b"OTTO": ("opentype", "font/otf"),  # CFF (OpenType) outlines
}

_NAME_FAMILY = 1  # nameID 1: Font Family name
_NAME_TYPOGRAPHIC_FAMILY = 16  # nameID 16: Typographic (preferred) Family name

_SFNT_HEADER_LEN = 12  # offsetTable: flavor(4) + numTables(2) + 3x uint16


def _decode_name_record(platform_id: int, raw: bytes) -> str | None:
    """Decode a name-table string per its platform's encoding."""
    try:
        if platform_id in (0, 3):  # Unicode, Windows -> UTF-16BE
            return raw.decode("utf-16-be")
        if platform_id == 1:  # Macintosh -> (approximate as) Latin-1
            return raw.decode("latin-1")
    except UnicodeDecodeError:
        return None
    return None


def _read_family_from_sfnt(data: bytes) -> str | None:
    """Extract the family name from an in-memory sfnt (TrueType/OpenType) font."""
    if len(data) < _SFNT_HEADER_LEN:
        return None
    num_tables = struct.unpack(">H", data[4:6])[0]

    name_offset = None
    for i in range(num_tables):
        rec = 12 + i * 16
        tag = data[rec : rec + 4]
        if tag == b"name":
            name_offset = struct.unpack(">I", data[rec + 8 : rec + 12])[0]
            break
    if name_offset is None:
        return None

    count, string_offset = struct.unpack(">HH", data[name_offset + 2 : name_offset + 6])
    storage = name_offset + string_offset

    # Prefer the typographic family (nameID 16) over the basic family (nameID 1),
    # since that is the name CSS/users normally reference for multi-weight families.
    candidates: dict[int, str] = {}
    for i in range(count):
        rec = name_offset + 6 + i * 12
        platform_id, _enc, _lang, name_id, length, offset = struct.unpack(
            ">HHHHHH",
            data[rec : rec + 12],
        )
        if name_id not in (_NAME_FAMILY, _NAME_TYPOGRAPHIC_FAMILY):
            continue
        raw = data[storage + offset : storage + offset + length]
        decoded = _decode_name_record(platform_id, raw)
        if decoded and name_id not in candidates:
            candidates[name_id] = decoded.strip()

    return candidates.get(_NAME_TYPOGRAPHIC_FAMILY) or candidates.get(_NAME_FAMILY)


def _woff_to_sfnt(data: bytes) -> bytes:
    """
    Reassemble an sfnt blob from a WOFF (v1) container, enough to read names.

    Only the ``name`` table's bytes need to be valid for family extraction, but
    rebuilding the full table directory keeps the parser identical to sfnt.
    """
    flavor = data[4:8]
    num_tables = struct.unpack(">H", data[12:14])[0]

    # WOFF table directory entries are 20 bytes: tag, offset, compLength,
    # origLength, origChecksum.
    tables = []
    for i in range(num_tables):
        rec = 44 + i * 20
        tag, offset, comp_len, orig_len, _ = struct.unpack(
            ">4sIIII",
            data[rec : rec + 20],
        )
        blob = data[offset : offset + comp_len]
        if comp_len != orig_len:
            blob = zlib.decompress(blob)
        tables.append((tag, blob))

    # Rebuild a minimal sfnt: header + directory + concatenated tables.
    out = bytearray()
    out += flavor
    out += struct.pack(">H", num_tables)
    out += struct.pack(">HHH", 0, 0, 0)  # searchRange/entrySelector/rangeShift (unused)

    body = bytearray()
    body_base = 12 + num_tables * 16
    for tag, blob in tables:
        offset = body_base + len(body)
        out += struct.pack(">4sIII", tag, 0, offset, len(blob))
        body += blob
        body += b"\x00" * (-len(blob) % 4)  # 4-byte align
    out += body
    return bytes(out)


def font_face_from_path(path: str | Path) -> FontFace:
    """
    Build an ``@font-face`` descriptor from a font file on disk.

    Args:
        path: Path to a ``.ttf``, ``.otf``, or ``.woff`` font file.

    Returns:
        A dict with ``family`` (read from the font), ``format`` (``@font-face``
        ``format()`` hint), and ``url`` (a base64 ``data:`` URL).

    Raises:
        FileNotFoundError: If the path does not exist.
        ValueError: If the font format is unsupported or the family name cannot
            be read.

    """
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Font file not found: {path}")

    data = path.read_bytes()
    signature = data[:4]

    if signature == b"wOFF":
        fmt, mime = "woff", "font/woff"
        family = _read_family_from_sfnt(_woff_to_sfnt(data))
    elif signature == b"wOF2":
        raise ValueError(
            f"{path.name}: .woff2 fonts are not supported (they require a Brotli "
            "decoder). Supply the .ttf, .otf, or .woff version of the font.",
        )
    elif signature in _SFNT_FLAVORS:
        fmt, mime = _SFNT_FLAVORS[signature]
        family = _read_family_from_sfnt(data)
    elif signature == b"ttcf":
        raise ValueError(
            f"{path.name}: TrueType/OpenType Collections (.ttc) are not "
            "supported. Supply a single-font .ttf or .otf file.",
        )
    else:
        raise ValueError(
            f"{path.name}: unrecognized font format (signature {signature!r}). "
            "Supported formats: .ttf, .otf, .woff.",
        )

    if not family:
        raise ValueError(
            f"{path.name}: could not read a font family name from the font's "
            "'name' table.",
        )

    encoded = base64.b64encode(data).decode("ascii")
    _logger.debug(f"Prepared font '{family}' ({fmt}) from {path}")
    return {
        "family": family,
        "format": fmt,
        "url": f"data:{mime};base64,{encoded}",
    }
