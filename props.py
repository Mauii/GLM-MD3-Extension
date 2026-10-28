from __future__ import annotations

from typing import Optional

from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    IntProperty,
    StringProperty,
)
from bpy.types import PropertyGroup

from .constants import MODEL_CATEGORIES
from .index import clear_index, ensure_index, get_base_dir
from .skin import format_skin_label

MODEL_CATEGORY_LABELS = {
    "chunks": "Chunks",
    "flags": "Flags",
    "items": "Items",
    "map_objects": "map_objects",
    "players": "Players",
    "weaphits": "weaphits",
    "weapons2": "weapons2",
}


def clear_skin(props):
    try:
        props.property_unset("skin_name")
    except Exception:
        props.skin_name = ""


def get_selected_model_item(props):
    index = props.active_model_index
    if index < 0 or index >= len(props.model_items):
        return None
    item = props.model_items[index]
    return None if item.is_header else item


def get_selected_model_from_props(props) -> Optional[str]:
    item = get_selected_model_item(props)
    if props.model_type != "players" or item is None:
        return None
    return item.name


def on_model_index_changed(self, context):
    item = get_selected_model_item(self)
    if self.model_type != "players" or item is None:
        clear_skin(self)
        return None
    try:
        index = ensure_index(get_base_dir(self.game_path))
        entry = index["models"].get(item.name) if index else None
        if entry and entry["skins"]:
            self.skin_name = entry["skins"][0].as_posix()
        else:
            clear_skin(self)
    except Exception as exc:  # noqa: BLE001
        print(f"model index update failed: {exc}")
    return None


def update_game_path(self, context):
    clear_index()
    refresh_model_list(context)


def update_search(self, context):
    refresh_model_list(context)


def update_model_type(self, context):
    refresh_model_list(context)


def update_model_index(self, context):
    index = self.active_model_index
    if 0 <= index < len(self.model_items) and self.model_items[index].is_header:
        selectable = next(
            (
                i
                for i in range(index + 1, len(self.model_items))
                if not self.model_items[i].is_header
            ),
            None,
        )
        if selectable is None:
            selectable = next(
                (
                    i
                    for i in range(index - 1, -1, -1)
                    if not self.model_items[i].is_header
                ),
                -1,
            )
        self.active_model_index = selectable
        return None
    return on_model_index_changed(self, context)


def _add_model_item(props, *, name, label, category, source, rel_path, file_format):
    item = props.model_items.add()
    item.name = name
    item.label = label
    item.category = category
    item.source = source
    item.rel_path = rel_path.as_posix()
    item.file_format = file_format
    item.is_header = False


def _add_header_item(props, label):
    item = props.model_items.add()
    item.name = ""
    item.label = label
    item.category = "map_objects"
    item.source = ""
    item.rel_path = ""
    item.file_format = ""
    item.is_header = True


def refresh_model_list(context) -> None:
    if not context or not getattr(context, "scene", None):
        return
    props = context.scene.pk3_browser
    index = ensure_index(get_base_dir(props.game_path))
    props.model_items.clear()
    clear_skin(props)
    if not index:
        props.active_model_index = -1
        return

    filter_text = props.search.lower().strip()
    if props.model_type == "players":
        for name in sorted(index["models"]):
            if filter_text and filter_text not in name.lower():
                continue
            primary = index["models"][name]["primary"]
            source = (
                "disk"
                if primary.origin == "disk"
                else primary.container.name if primary.container else "pk3"
            )
            _add_model_item(
                props,
                name=name,
                label=name,
                category="players",
                source=source,
                rel_path=primary.glm,
                file_format="glm",
            )
    else:
        entries = index["category_models"].get(props.model_type, {})
        models = sorted(
            entries.values(),
            key=lambda entry: (
                entry["group"].lower(),
                entry["label"].lower(),
                entry["name"],
            ),
        )
        if props.model_type in {"map_objects", "weapons2"}:
            groups = {}
            for entry in models:
                if (
                    filter_text
                    and filter_text not in entry["group"].lower()
                    and filter_text not in entry["label"].lower()
                ):
                    continue
                groups.setdefault(entry["group"], []).append(entry)
            for group in sorted(groups, key=str.lower):
                _add_header_item(props, group)
                for entry in groups[group]:
                    _add_model_item(
                        props,
                        name=entry["name"],
                        label=entry["label"],
                        category=props.model_type,
                        source=entry["source"],
                        rel_path=entry["rel_path"],
                        file_format=entry["format"],
                    )
        else:
            for entry in models:
                if filter_text and filter_text not in entry["label"].lower():
                    continue
                _add_model_item(
                    props,
                    name=entry["name"],
                    label=entry["label"],
                    category=props.model_type,
                    source=entry["source"],
                    rel_path=entry["rel_path"],
                    file_format=entry["format"],
                )

    first_selectable = next(
        (i for i, item in enumerate(props.model_items) if not item.is_header),
        -1,
    )
    props.active_model_index = first_selectable
    on_model_index_changed(props, context)


def model_type_enum_items(self, context):
    return [
        (category, MODEL_CATEGORY_LABELS[category], f"Show {MODEL_CATEGORY_LABELS[category].lower()}")
        for category in MODEL_CATEGORIES
    ]


def skin_enum_items(self, context):
    try:
        props = context.scene.pk3_browser if context and getattr(context, "scene", None) else self
    except Exception:
        props = self
    model_name = get_selected_model_from_props(props) if hasattr(props, "model_items") else None
    if not model_name:
        return [("", "No player model selected", "")]
    index = ensure_index(get_base_dir(getattr(props, "game_path", "")))
    entry = index["models"].get(model_name) if index else None
    if not entry or not entry["skins"]:
        return [("", "No .skin files", "")]
    return [
        (rel.as_posix(), format_skin_label(rel), rel.as_posix())
        for rel in entry["skins"]
    ]


def ensure_skin_selected(props, *, assign: bool = True):
    if props.model_type != "players":
        if assign:
            clear_skin(props)
        return None
    index = ensure_index(get_base_dir(props.game_path))
    model_name = get_selected_model_from_props(props)
    entry = index["models"].get(model_name) if index and model_name else None
    if not entry or not entry["skins"]:
        if assign:
            clear_skin(props)
        return None
    valid = [rel.as_posix() for rel in entry["skins"]]
    if props.skin_name not in valid:
        if assign:
            props.skin_name = valid[0]
        return valid[0]
    return props.skin_name


class PK3ModelItem(PropertyGroup):
    name: StringProperty() # pyright: ignore[reportInvalidTypeForm]
    label: StringProperty() # pyright: ignore[reportInvalidTypeForm]
    category: StringProperty() # pyright: ignore[reportInvalidTypeForm]
    source: StringProperty() # pyright: ignore[reportInvalidTypeForm]
    rel_path: StringProperty() # pyright: ignore[reportInvalidTypeForm]
    file_format: StringProperty() # pyright: ignore[reportInvalidTypeForm]
    is_header: BoolProperty(default=False) # pyright: ignore[reportInvalidTypeForm]


class PK3BrowserProperties(PropertyGroup):
    game_path: StringProperty(
        name="Game Path",
        description="Path to the game folder (GameData or base)",
        subtype="DIR_PATH",
        update=update_game_path,
    ) # pyright: ignore[reportInvalidTypeForm]
    model_type: EnumProperty(
        name="Model Type",
        description="Choose a model folder to browse",
        items=model_type_enum_items,
        default=4,
        update=update_model_type,
    ) # pyright: ignore[reportInvalidTypeForm]
    search: StringProperty(
        name="Search",
        description="Filter models",
        default="",
        update=update_search,
    ) # pyright: ignore[reportInvalidTypeForm]
    model_items: CollectionProperty(type=PK3ModelItem) # pyright: ignore[reportInvalidTypeForm]
    active_model_index: IntProperty(
        name="Model Index",
        default=-1,
        update=update_model_index,
    ) # pyright: ignore[reportInvalidTypeForm]
    skin_name: EnumProperty(
        name="Skin File",
        description="Select a skin before importing",
        items=skin_enum_items,
    ) # pyright: ignore[reportInvalidTypeForm]
    model_extract_dir: StringProperty(
        name="Extract To",
        description="Folder to extract the selected model into",
        subtype="DIR_PATH",
    ) # pyright: ignore[reportInvalidTypeForm]
