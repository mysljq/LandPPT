import struct
from pathlib import Path

from landppt.web.route_modules.export_routes import _font_embedding_allowed


def _write_sfnt(path: Path, fs_type: int) -> None:
    os2_offset = 28
    header = struct.pack(">IHHHH", 0x00010000, 1, 0, 0, 0)
    record = struct.pack(">4sIII", b"OS/2", 0, os2_offset, 10)
    os2_table = b"\0" * 8 + struct.pack(">H", fs_type)
    path.write_bytes(header + record + os2_table)


def test_export_font_license_allows_installable_and_editable(tmp_path):
    installable = tmp_path / "installable.ttf"
    editable = tmp_path / "editable.ttf"
    _write_sfnt(installable, 0)
    _write_sfnt(editable, 0x0008)

    assert _font_embedding_allowed(installable)
    assert _font_embedding_allowed(editable)


def test_export_font_license_rejects_restricted_and_bitmap_only(tmp_path):
    restricted = tmp_path / "restricted.ttf"
    bitmap_only = tmp_path / "bitmap-only.ttf"
    _write_sfnt(restricted, 0x0002)
    _write_sfnt(bitmap_only, 0x0200)

    assert not _font_embedding_allowed(restricted)
    assert not _font_embedding_allowed(bitmap_only)
