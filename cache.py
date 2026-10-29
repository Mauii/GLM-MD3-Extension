from __future__ import annotations

import shutil
from pathlib import Path
from typing import Dict, List, Tuple

import bpy

from . import pk3
from .constants import TEXTURE_EXTS
from .index import normalize_rel
from .data_types import FileSource
from .texture_formats import load_texture


def clear_cached_textures(cache_root: Path) -> None:
    if not cache_root.exists():
        return
    for file in cache_root.rglob("*"):
        if file.is_file() and file.suffix.lower() in TEXTURE_EXTS:
            file.unlink()
    dirs = sorted(
        (path for path in cache_root.rglob("*") if path.is_dir()),
        key=lambda path: len(path.parts),
        reverse=True,
    )
    for directory in dirs:
        if not any(directory.iterdir()):
            directory.rmdir()


def cleanup_cache(cache_root: Path, keep_set: set[str]) -> None:
    if not cache_root.exists():
        return
    for file in cache_root.rglob("*"):
        if file.is_file():
            rel_norm = normalize_rel(file.relative_to(cache_root))
            if rel_norm not in keep_set:
                try:
                    file.unlink()
                except FileNotFoundError:
                    pass
    dirs = sorted([p for p in cache_root.rglob("*") if p.is_dir()], key=lambda p: len(p.parts), reverse=True)
    for d in dirs:
        try:
            if not any(d.iterdir()):
                d.rmdir()
        except OSError:
            pass


def extract_assets(
    base_dir: Path,
    cache_root: Path,
    assets: List[Tuple[FileSource, Path]],
    *,
    clean_stale: bool = True,
):
    cache_root.mkdir(parents=True, exist_ok=True)
    texture_map: Dict[str, str] = {}
    keep: set[str] = set()
    failed: List[str] = []
    for src, dest_rel in assets:
        keep.add(normalize_rel(dest_rel))
        dest_path = cache_root / dest_rel
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            if src.origin == "disk":
                shutil.copy2(base_dir / src.rel_path, dest_path)
            else:
                with pk3.open_pk3(src.container) as zf:
                    with zf.open(src.rel_path.as_posix()) as handle, open(dest_path, "wb") as outfile:
                        shutil.copyfileobj(handle, outfile)
        except Exception as exc:  # noqa: BLE001
            print(f"Failed to extract {dest_rel}: {exc}")
            failed.append(str(dest_rel))
            continue
        if dest_path.suffix.lower() in TEXTURE_EXTS:
            texture_map[dest_path.stem.lower()] = str(dest_path)
    if clean_stale:
        cleanup_cache(cache_root, keep)
    return texture_map, failed


def rewrite_skin_paths(cache_root: Path, skin_rel: Path, replacements: Dict[str, str]) -> None:
    if not replacements:
        return
    skin_path = cache_root / skin_rel
    if not skin_path.exists():
        return
    try:
        text = skin_path.read_text()
    except Exception:
        return
    for orig, new in replacements.items():
        text = text.replace(orig, new)
    try:
        skin_path.write_text(text)
    except Exception:
        pass


def relink_images_from_cache(texture_map: Dict[str, str]) -> None:
    if not texture_map:
        return
    for img in list(bpy.data.images):
        stem = Path(img.name).stem.lower()
        if stem in texture_map:
            new_path = texture_map[stem]
            try:
                loaded = load_texture(new_path, check_existing=True)
            except Exception as exc:  # noqa: BLE001
                print(f"Failed to load cached texture {new_path}: {exc}")
                continue
            if loaded != img:
                img.user_remap(loaded)
