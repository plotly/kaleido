"""Tests for kaleido._utils.font_tools (custom font embedding).

The font parser only needs a valid ``name`` table to extract a family, so the
helpers below build the smallest possible sfnt/WOFF containers carrying name
records. This keeps the tests free of any real font-file fixtures.
"""

import base64
import struct

import pytest

from kaleido._utils import fig_tools, font_tools

NAME_FAMILY = 1  # nameID 1: Font Family name
NAME_TYPOGRAPHIC = 16  # nameID 16: Typographic Family name
WOFF_HEADER_LEN = 44


def _name_table(records):
    """Build a minimal sfnt 'name' table from (name_id, family) records.

    Records are emitted as platform 3 (Windows / UTF-16BE) entries.
    """
    storage_offset = 6 + 12 * len(records)
    header = struct.pack(">HHH", 0, len(records), storage_offset)

    recs = b""
    storage = b""
    for name_id, family in records:
        raw = family.encode("utf-16-be")
        recs += struct.pack(">HHHHHH", 3, 1, 0x409, name_id, len(raw), len(storage))
        storage += raw
    return header + recs + storage


def _sfnt(records, flavor=b"\x00\x01\x00\x00"):
    """Build a minimal single-table ('name') sfnt font."""
    if isinstance(records, str):
        records = [(NAME_FAMILY, records)]
    name_tbl = _name_table(records)
    name_offset = 12 + 16  # header(12) + one dir entry(16)
    header = flavor + struct.pack(">HHHH", 1, 0, 0, 0)  # numTables=1, then unused
    directory = struct.pack(">4sIII", b"name", 0, name_offset, len(name_tbl))
    return header + directory + name_tbl


def _woff(family, flavor=b"\x00\x01\x00\x00"):
    """Build a minimal single-table WOFF (v1) container (name table uncompressed)."""
    name_tbl = _name_table([(NAME_FAMILY, family)])
    table_offset = WOFF_HEADER_LEN + 20  # header + one dir entry(20)
    header = b"wOFF" + flavor + b"\x00" * 4 + struct.pack(">H", 1) + b"\x00" * 30
    assert len(header) == WOFF_HEADER_LEN
    directory = struct.pack(
        ">4sIIII",
        b"name",
        table_offset,
        len(name_tbl),  # compLength == origLength -> stored uncompressed
        len(name_tbl),
        0,
    )
    return header + directory + name_tbl


# --- family extraction -------------------------------------------------------


def test_ttf_family_and_format(tmp_path):
    f = tmp_path / "Test.ttf"
    f.write_bytes(_sfnt("My Test Font"))
    face = font_tools.font_face_from_path(f)
    assert face["family"] == "My Test Font"
    assert face["format"] == "truetype"
    assert face["url"].startswith("data:font/ttf;base64,")
    # url must round-trip to the original bytes
    b64 = face["url"].split(",", 1)[1]
    assert base64.b64decode(b64) == f.read_bytes()


def test_otf_uses_opentype_hint(tmp_path):
    f = tmp_path / "Test.otf"
    f.write_bytes(_sfnt("CFF Font", flavor=b"OTTO"))
    face = font_tools.font_face_from_path(f)
    assert face["family"] == "CFF Font"
    assert face["format"] == "opentype"
    assert face["url"].startswith("data:font/otf;base64,")


def test_woff_is_decoded(tmp_path):
    f = tmp_path / "Test.woff"
    f.write_bytes(_woff("Woffy"))
    face = font_tools.font_face_from_path(f)
    assert face["family"] == "Woffy"
    assert face["format"] == "woff"
    assert face["url"].startswith("data:font/woff;base64,")


def test_typographic_family_preferred_over_basic(tmp_path):
    """nameID 16 (typographic) should win over nameID 1 (basic) when both exist."""
    f = tmp_path / "Multi.ttf"
    f.write_bytes(_sfnt([(NAME_FAMILY, "Basic"), (NAME_TYPOGRAPHIC, "Typographic")]))
    assert font_tools.font_face_from_path(f)["family"] == "Typographic"


# --- error paths -------------------------------------------------------------


def test_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        font_tools.font_face_from_path(tmp_path / "nope.ttf")


def test_woff2_rejected(tmp_path):
    f = tmp_path / "Test.woff2"
    f.write_bytes(b"wOF2" + b"\x00" * 32)
    with pytest.raises(ValueError, match="woff2"):
        font_tools.font_face_from_path(f)


def test_ttc_rejected(tmp_path):
    f = tmp_path / "Test.ttc"
    f.write_bytes(b"ttcf" + b"\x00" * 32)
    with pytest.raises(ValueError, match=r"[Cc]ollection"):
        font_tools.font_face_from_path(f)


def test_unrecognized_format(tmp_path):
    f = tmp_path / "Test.bin"
    f.write_bytes(b"\xde\xad\xbe\xef" + b"\x00" * 32)
    with pytest.raises(ValueError, match="unrecognized"):
        font_tools.font_face_from_path(f)


def test_missing_name_table(tmp_path):
    """A valid sfnt signature but no readable family name is an error."""
    # numTables=0 -> no name table at all.
    f = tmp_path / "NoName.ttf"
    f.write_bytes(b"\x00\x01\x00\x00" + struct.pack(">HHHH", 0, 0, 0, 0))
    with pytest.raises(ValueError, match="family name"):
        font_tools.font_face_from_path(f)


# --- integration with coerce_for_js ------------------------------------------


def test_coerce_for_js_packages_fonts(tmp_path):
    """opts['fonts'] paths should become FontFace descriptors in the spec."""
    f = tmp_path / "Inter.ttf"
    f.write_bytes(_sfnt("Inter"))
    fig = {"data": [], "layout": {}}
    spec = fig_tools.coerce_for_js(fig, None, {"format": "svg", "fonts": [f]})
    assert "fonts" in spec
    assert spec["fonts"][0]["family"] == "Inter"
    assert spec["fonts"][0]["format"] == "truetype"


def test_coerce_for_js_omits_fonts_when_absent():
    """No 'fonts' key in the spec when none were requested."""
    spec = fig_tools.coerce_for_js({"data": [], "layout": {}}, None, {"format": "svg"})
    assert "fonts" not in spec
