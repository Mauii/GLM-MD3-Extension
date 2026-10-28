from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import pk3
from .constants import MODEL_CATEGORIES, TEXTURE_EXTS
from .data_types import FileSource, ModelSource

PK3_INDEX_CACHE: Optional[Dict] = None


def normalize_rel(path: Path | str) -> str:
    return str(Path(path).as_posix()).lower().lstrip("./")


def get_base_dir(path_str: str) -> Path:
    if not path_str:
        return Path()
    base = Path(path_str).expanduser()
    if (base / "base").is_dir():
        base = base / "base"
    return base


def should_skip_pk3(pk3_path: Path) -> bool:
    # We currently include all pk3 files.
    return False


def source_priority(src: ModelSource) -> Tuple[int, int]:
    if src.origin == "disk":
        return (0, 0)
    if src.container and src.container.name.lower() == "assets1.pk3":
        return (1, 0)
    return (1, 1)


def clear_index() -> None:
    global PK3_INDEX_CACHE
    PK3_INDEX_CACHE = None


def ensure_index(base_dir: Path) -> Optional[Dict]:
    global PK3_INDEX_CACHE
    if not base_dir or not base_dir.exists():
        PK3_INDEX_CACHE = None
        return None
    if PK3_INDEX_CACHE and PK3_INDEX_CACHE.get("base") == base_dir:
        return PK3_INDEX_CACHE
    PK3_INDEX_CACHE = build_index(base_dir)
    return PK3_INDEX_CACHE


def build_index(base_dir: Path) -> Dict:
    models_tmp: Dict[str, Dict] = {}
    category_models: Dict[str, Dict[str, Dict]] = {
        category: {} for category in MODEL_CATEGORIES if category != "players"
    }
    textures_by_rel: Dict[str, List[FileSource]] = {}
    textures_by_stem: Dict[str, List[FileSource]] = {}
    textures_by_dir: Dict[str, List[FileSource]] = {}
    gla_index: Dict[str, List[FileSource]] = {}

    def add_texture(rel: Path, origin: str, container: Optional[Path]):
        fs = FileSource(origin, container, rel)
        textures_by_rel.setdefault(normalize_rel(rel), []).append(fs)
        textures_by_stem.setdefault(rel.stem.lower(), []).append(fs)
        textures_by_dir.setdefault(normalize_rel(rel.parent), []).append(fs)

    def add_gla(rel: Path, origin: str, container: Optional[Path]):
        fs = FileSource(origin, container, rel)
        gla_index.setdefault(normalize_rel(rel), []).append(fs)

    def get_entry(name: str) -> Dict:
        return models_tmp.setdefault(name, {"sources": {}, "skins": set()})

    def add_category_model(rel: Path, origin: str, container: Optional[Path]) -> None:
        if len(rel.parts) < 3 or rel.parts[0].lower() != "models":
            return
        category = rel.parts[1].lower()
        if category not in category_models or rel.suffix.lower() not in {".glm", ".md3"}:
            return

        if category == "map_objects":
            if len(rel.parts) < 4:
                return
            group = rel.parts[2]
            key = normalize_rel(rel)
            label = rel.name
        elif category == "weapons2":
            if len(rel.parts) < 4:
                return
            group = rel.parts[2]
            key = normalize_rel(rel)
            label = rel.name
        else:
            group = ""
            key = normalize_rel(rel)
            label = rel.stem

        entries = category_models[category]
        existing = entries.get(key)
        priority = 0 if origin == "disk" else 1
        format_priority = 0 if rel.suffix.lower() == ".md3" else 1
        if existing and (
            existing["priority"],
            existing["format_priority"],
        ) <= (priority, format_priority):
            return
        entries[key] = {
            "name": key,
            "label": label,
            "group": group,
            "source": "disk" if origin == "disk" else container.name if container else "pk3",
            "origin": origin,
            "container": container,
            "rel_path": rel,
            "format": rel.suffix.lower()[1:],
            "priority": priority,
            "format_priority": format_priority,
        }

    # Scan PK3 archives
    for pk3_path in sorted(base_dir.rglob("*.pk3")):
        if should_skip_pk3(pk3_path):
            continue
        try:
            with pk3.open_pk3(pk3_path) as zf:
                for info in zf.infolist():
                    if info.is_dir():
                        continue
                    rel = Path(info.filename)
                    suffix = rel.suffix.lower()
                    if suffix in TEXTURE_EXTS:
                        add_texture(rel, "pk3", pk3_path)
                        continue
                    add_category_model(rel, "pk3", pk3_path)
                    if len(rel.parts) < 3:
                        continue
                    if rel.parts[0].lower() != "models" or rel.parts[1].lower() != "players":
                        continue
                    entry = get_entry(rel.parts[2])
                    source = entry["sources"].get(pk3_path)
                    if not source:
                        source = ModelSource("pk3", pk3_path)
                        entry["sources"][pk3_path] = source
                    if suffix == ".glm":
                        if source.glm is None or rel.name.lower() == "model.glm":
                            source.glm = rel
                    elif suffix == ".skin":
                        source.skins.add(rel)
                        entry["skins"].add(rel)
                    elif suffix == ".gla":
                        source.glas.add(rel)
                        add_gla(rel, "pk3", pk3_path)
                    elif suffix in TEXTURE_EXTS:
                        add_texture(rel, "pk3", pk3_path)
        except pk3.ArchiveError:
            print(f"Skipping invalid pk3: {pk3_path}")
            continue

    # Scan disk models
    models_root = base_dir / "models"
    if models_root.is_dir():
        for category_dir in models_root.iterdir():
            if not category_dir.is_dir() or category_dir.name.lower() == "players":
                continue
            if category_dir.name.lower() not in category_models:
                continue
            for model_file in category_dir.rglob("*"):
                if model_file.is_file():
                    rel = model_file.relative_to(base_dir)
                    if model_file.suffix.lower() in TEXTURE_EXTS:
                        add_texture(rel, "disk", None)
                    else:
                        add_category_model(rel, "disk", None)

    models_dir = base_dir / "models" / "players"
    if models_dir.is_dir():
        for model_dir in models_dir.iterdir():
            if not model_dir.is_dir():
                continue
            glm_files = list(model_dir.glob("*.glm"))
            if not glm_files:
                continue
            glm_file = next((p for p in glm_files if p.name.lower() == "model.glm"), glm_files[0])
            entry = get_entry(model_dir.name)
            key = model_dir
            source = entry["sources"].get(key)
            if not source:
                source = ModelSource("disk", None)
                entry["sources"][key] = source
            source.glm = glm_file.relative_to(base_dir)
            for skin_path in model_dir.glob("*.skin"):
                rel = skin_path.relative_to(base_dir)
                source.skins.add(rel)
                entry["skins"].add(rel)
            for gla_path in model_dir.glob("*.gla"):
                rel = gla_path.relative_to(base_dir)
                source.glas.add(rel)
                add_gla(rel, "disk", None)
            for tex in model_dir.rglob("*"):
                if tex.is_file() and tex.suffix.lower() in TEXTURE_EXTS:
                    add_texture(tex.relative_to(base_dir), "disk", None)

    # Scan loose textures under /textures
    textures_dir = base_dir / "textures"
    if textures_dir.is_dir():
        for tex in textures_dir.rglob("*"):
            if tex.is_file() and tex.suffix.lower() in TEXTURE_EXTS:
                add_texture(tex.relative_to(base_dir), "disk", None)

    models: Dict[str, Dict] = {}
    for name, data in models_tmp.items():
        sources_list = list(data["sources"].values())
        glm_sources = [s for s in sources_list if s.glm]
        if not glm_sources:
            continue
        primary = sorted(glm_sources, key=source_priority)[0]
        skins = sorted({Path(s) for src in sources_list for s in src.skins}, key=lambda p: p.as_posix().lower())
        models[name] = {"sources": sources_list, "primary": primary, "skins": skins}

    return {
        "base": base_dir,
        "models": models,
        "category_models": category_models,
        "textures_by_rel": textures_by_rel,
        "textures_by_stem": textures_by_stem,
        "textures_by_dir": textures_by_dir,
        "gla_index": gla_index,
    }
