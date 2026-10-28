from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import pk3
from .constants import TEXTURE_EXTS
from .index import normalize_rel
from .data_types import FileSource, ModelSource


def format_skin_label(rel: Path) -> str:
    stem = rel.stem
    if stem.startswith("model_"):
        return stem[len("model_") :]
    return stem


def parse_skin_text(text: str) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("//"):
            continue
        if "," not in line:
            continue
        part, tex = line.split(",", 1)
        part = part.strip()
        tex = tex.strip()
        if tex.lower() in {"*off", "off"}:
            continue
        if part:
            mapping[part] = tex
    return mapping


def read_text_from_source(source: FileSource, base_dir: Path) -> str:
    if source.origin == "disk":
        return (base_dir / source.rel_path).read_text(errors="ignore")
    with pk3.open_pk3(source.container) as zf:
        with zf.open(source.rel_path.as_posix()) as handle:
            return handle.read().decode("utf-8", errors="ignore")


def resolve_texture(
    index: Dict, tex_entry: str, preferred: Optional[ModelSource] = None
) -> Optional[Tuple[FileSource, Path]]:
    tex_path = Path(tex_entry)

    def choose(fs_list: List[FileSource]) -> FileSource:
        if preferred and preferred.container:
            for fs in fs_list:
                if fs.container == preferred.container:
                    return fs
        for fs in fs_list:
            if fs.origin == "disk":
                return fs
        return fs_list[0]

    for ext in TEXTURE_EXTS:
        candidate = tex_path.with_suffix(ext)
        norm = normalize_rel(candidate)
        if norm in index["textures_by_rel"]:
            fs = choose(index["textures_by_rel"][norm])
            return fs, fs.rel_path

    stem = tex_path.stem.lower()
    if stem in index["textures_by_stem"]:
        fs = choose(index["textures_by_stem"][stem])
        return fs, fs.rel_path
    return None


def resolve_gla(index: Dict, rel_path: Path) -> Optional[FileSource]:
    norm = normalize_rel(rel_path)
    if norm in index["gla_index"]:
        return index["gla_index"][norm][0]
    return None


def find_gla(index: Dict, model_name: str, entry: Dict) -> Optional[FileSource]:
    for src in entry["sources"]:
        for gla_rel in src.glas:
            resolved = resolve_gla(index, gla_rel)
            if resolved:
                return resolved
    for cand in (
        Path(f"models/players/{model_name}/{model_name}.gla"),
        Path(f"models/players/{model_name}/model.gla"),
        Path("models/players/_humanoid/_humanoid.gla"),
    ):
        resolved = resolve_gla(index, cand)
        if resolved:
            return resolved
    return None


def find_skin_source(entry: Dict, skin_rel: Path) -> Optional[FileSource]:
    target_norm = normalize_rel(skin_rel)
    for src in entry["sources"]:
        for candidate in src.skins:
            if normalize_rel(candidate) == target_norm:
                return FileSource(src.origin, src.container, Path(candidate))
    return None


def derive_skin_suffix(skin_rel: Path) -> str:
    stem = skin_rel.stem
    if stem.startswith("model_"):
        return stem[len("model_") :]
    return stem


def collect_model_texture_assets(index: Dict, model_name: str):
    entry = index["models"].get(model_name)
    if not entry:
        return []
    primary: ModelSource = entry["primary"]
    rel_dirs: set[str] = set()
    if primary.glm:
        rel_dirs.add(normalize_rel(primary.glm.parent))
    for src in entry["sources"]:
        if src.glm:
            rel_dirs.add(normalize_rel(src.glm.parent))
        for skin in src.skins:
            rel_dirs.add(normalize_rel(Path(skin).parent))
        for gla in src.glas:
            rel_dirs.add(normalize_rel(Path(gla).parent))
    rel_dirs.add("textures")

    assets: List[Tuple[FileSource, Path]] = []
    seen: set[str] = set()
    for rel_dir in sorted(rel_dirs):
        for fs in index["textures_by_dir"].get(rel_dir, []):
            norm = normalize_rel(fs.rel_path)
            if norm in seen:
                continue
            seen.add(norm)
            assets.append((fs, fs.rel_path))
    return assets


def collect_assets_for_skin(index: Dict, base_dir: Path, model_name: str, skin_rel: Path):
    entry = index["models"].get(model_name)
    if not entry:
        raise ValueError("Model not found")
    skin_src = find_skin_source(entry, skin_rel)
    if not skin_src:
        raise ValueError("Skin file not found")
    primary: ModelSource = entry["primary"]
    glm_src = FileSource(primary.origin, primary.container, primary.glm)
    skin_text = read_text_from_source(skin_src, base_dir)
    skin_map = parse_skin_text(skin_text)
    textures: List[Tuple[FileSource, Path]] = []
    missing: List[str] = []
    replacements: Dict[str, str] = {}
    for tex in skin_map.values():
        resolved = resolve_texture(index, tex, primary)
        if resolved:
            textures.append(resolved)
            fs, actual_rel = resolved
            if actual_rel.as_posix() != tex:
                replacements[tex] = actual_rel.as_posix()
        else:
            missing.append(tex)
    assets: List[Tuple[FileSource, Path]] = [
        (glm_src, glm_src.rel_path),
        (skin_src, skin_rel),
    ]
    gla_src = find_gla(index, model_name, entry)
    if gla_src:
        assets.append((gla_src, gla_src.rel_path))
    for model_tex in collect_model_texture_assets(index, model_name):
        assets.append(model_tex)
    for texture in textures:
        rel_name = normalize_rel(texture[1])
        if not any(normalize_rel(existing[1]) == rel_name for existing in assets):
            assets.append(texture)
    return assets, missing, replacements
