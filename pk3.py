"""Helpers for reading PK3 archives in the Blender add-on."""

from pathlib import Path
from zipfile import BadZipFile, ZipFile


class ArchiveError(Exception):
    """Raised when a PK3 archive cannot be read."""


def open_pk3(path: Path) -> ZipFile:
    if not path.exists():
        raise ArchiveError(f"File not found: {path}")
    try:
        return ZipFile(path)
    except BadZipFile as exc:
        raise ArchiveError(f"Not a valid PK3/ZIP archive: {path} ({exc})") from exc
