from __future__ import annotations

import bmesh
from math import ceil, radians
from pathlib import Path, PurePosixPath
import re
import shutil

import bpy
from bpy.props import BoolProperty, EnumProperty
from bpy.types import Operator
from bpy_extras import view3d_utils
from mathutils import Vector

from . import pk3
from .cache import (
    clear_cached_textures,
    extract_assets,
    relink_images_from_cache,
    rewrite_skin_paths,
)
from .constants import CACHE_FOLDER, TEXTURE_EXTS
from .data_types import FileSource
from .index import clear_index, ensure_index, get_base_dir
from .index import normalize_rel
from .props import (
    ensure_skin_selected,
    get_selected_model_from_props,
    get_selected_model_item,
    refresh_model_list,
)
from .skin import (
    collect_assets_for_skin,
    derive_skin_suffix,
    find_skin_source,
    is_skin_off,
    parse_skin_text,
    read_text_from_source,
    resolve_texture,
)
from .texture_formats import load_texture


def _is_camera_view(context) -> bool:
    space = context.space_data
    return (
        space is not None
        and space.type == "VIEW_3D"
        and space.region_3d is not None
        and space.region_3d.view_perspective == "CAMERA"
    )


def _materialize_model_file(base_dir: Path, entry: dict) -> Path:
    rel_path = Path(entry["rel_path"])
    if entry["origin"] == "disk":
        return base_dir / rel_path

    container = entry["container"]
    if container is None:
        raise ValueError(f"No PK3 archive is recorded for {rel_path}")

    destination = base_dir / CACHE_FOLDER / rel_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    with pk3.open_pk3(container) as archive:
        with archive.open(rel_path.as_posix()) as source, destination.open(
            "wb"
        ) as target:
            shutil.copyfileobj(source, target)
    return destination


def _extract_model_folder(
    base_dir: Path,
    folder_rel: Path,
    origin: str,
    container: Path | None,
    output_dir: Path,
    destination_rel: Path | None = None,
) -> int:
    source_dir = base_dir / folder_rel
    # AANPASSING: Gebruik direct output_dir als destination_rel niet is meegegeven
    destination_dir = output_dir / (destination_rel or Path("."))
    source_resolved = source_dir.resolve()
    destination_resolved = destination_dir.resolve()

    if origin == "disk":
        if not source_dir.is_dir():
            raise FileNotFoundError(f"Model folder not found: {source_dir}")
        if destination_resolved == source_resolved:
            return sum(1 for path in source_dir.rglob("*") if path.is_file())
        if source_resolved in destination_resolved.parents:
            raise ValueError("Choose an output folder outside the source model folder")
        copied = 0
        for source_file in source_dir.rglob("*"):
            if not source_file.is_file():
                continue
            relative_file = source_file.relative_to(source_dir)
            destination_file = destination_dir / relative_file
            destination_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_file, destination_file)
            copied += 1
        return copied

    if container is None:
        raise ValueError(f"No PK3 archive is recorded for {folder_rel}")

    folder_prefix = folder_rel.as_posix().rstrip("/") + "/"
    copied = 0
    with pk3.open_pk3(container) as archive:
        for info in archive.infolist():
            archive_name = info.filename.replace("\\", "/")
            if (
                info.is_dir()
                or not archive_name.casefold().startswith(folder_prefix.casefold())
            ):
                continue
            relative_name = archive_name[len(folder_prefix) :]
            relative_path = Path(relative_name)
            if (
                not relative_name
                or relative_path.is_absolute()
                or ".." in relative_path.parts
            ):
                continue
            destination_file = destination_dir / relative_path
            destination_file.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, destination_file.open("wb") as target:
                shutil.copyfileobj(source, target)
            copied += 1
    if copied == 0:
        raise FileNotFoundError(f"No files found in PK3 model folder: {folder_rel}")
    return copied


def _referenced_player_model_names(model_entry: dict, base_dir: Path) -> set[str]:
    texture_paths = []
    for source in model_entry["sources"]:
        for skin_path in source.skins:
            skin_source = FileSource(source.origin, source.container, Path(skin_path))
            skin_text = read_text_from_source(skin_source, base_dir)
            texture_paths.extend(
                texture
                for texture in parse_skin_text(skin_text).values()
                if not is_skin_off(texture)
            )

    ignore_stormtrooper = any(
        tuple(
            part.casefold()
            for part in PurePosixPath(path.replace("\\", "/")).parts[-2:]
        )
        == ("stormtrooper", "caps.tga")
        for path in texture_paths
    )
    referenced = {}
    for texture_path in texture_paths:
        parts = PurePosixPath(texture_path.replace("\\", "/")).parts
        if (
            len(parts) >= 4
            and parts[0].casefold() == "models"
            and parts[1].casefold() == "players"
        ):
            model_name = parts[2]
            if ignore_stormtrooper and model_name.casefold() == "stormtrooper":
                continue
            referenced.setdefault(model_name.casefold(), model_name)
    return set(referenced.values())


def _player_model_folder_source(
    base_dir: Path,
    model_name: str,
) -> tuple[Path, str, Path | None] | None:
    folder_rel = Path("models") / "players" / model_name
    loose_folder = base_dir / folder_rel
    if loose_folder.is_dir():
        return folder_rel, "disk", None

    folder_prefix = folder_rel.as_posix().casefold().rstrip("/") + "/"
    for archive_path in sorted(base_dir.rglob("*.pk3")):
        try:
            with pk3.open_pk3(archive_path) as archive:
                if any(
                    not info.is_dir()
                    and info.filename.replace("\\", "/")
                    .casefold()
                    .startswith(folder_prefix)
                    for info in archive.infolist()
                ):
                    return folder_rel, "pk3", archive_path
        except pk3.ArchiveError:
            continue
    return None


def _prepare_modview_directory(base_dir: Path) -> tuple[Path, int, list[str]]:
    folder_rel = Path("models") / "players" / "_humanoid"
    source_dir = base_dir / folder_rel
    destination_dir = base_dir / folder_rel
    source_resolved = source_dir.resolve()
    destination_resolved = destination_dir.resolve()
    if (
        source_resolved != destination_resolved
        and source_resolved in destination_resolved.parents
    ):
        raise ValueError("The ModView destination cannot be inside the source folder")

    destination_dir.mkdir(parents=True, exist_ok=True)
    copied_paths = set()
    if source_dir.is_dir():
        for source_file in source_dir.rglob("*"):
            if not source_file.is_file():
                continue
            relative_file = source_file.relative_to(source_dir)
            if source_resolved == destination_resolved:
                copied_paths.add(relative_file.as_posix().casefold())
                continue
            destination_file = destination_dir / relative_file
            destination_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_file, destination_file)
            copied_paths.add(relative_file.as_posix().casefold())

    folder_prefix = folder_rel.as_posix().casefold().rstrip("/") + "/"
    archive_failures = []
    for archive_path in sorted(base_dir.rglob("*.pk3")):
        try:
            with pk3.open_pk3(archive_path) as archive:
                for info in archive.infolist():
                    archive_name = info.filename.replace("\\", "/")
                    normalized_name = archive_name.casefold()
                    if info.is_dir() or not normalized_name.startswith(folder_prefix):
                        continue
                    relative_name = archive_name[len(folder_prefix) :]
                    relative_path = PurePosixPath(relative_name)
                    if (
                        not relative_name
                        or relative_path.is_absolute()
                        or ".." in relative_path.parts
                    ):
                        continue
                    relative_key = relative_path.as_posix().casefold()
                    if relative_key in copied_paths:
                        continue
                    destination_file = destination_dir.joinpath(*relative_path.parts)
                    destination_file.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(info) as source, destination_file.open("wb") as target:
                        shutil.copyfileobj(source, target)
                    copied_paths.add(relative_key)
        except pk3.ArchiveError as exc:
            archive_failures.append(f"{archive_path}: {exc}")

    if not copied_paths:
        raise FileNotFoundError(
            f"Could not find models/players/_humanoid in {base_dir} or its PK3 archives"
        )
    return destination_dir, len(copied_paths), archive_failures


def _get_md3_operator():
    try:
        operator = bpy.ops.import_scene.id3_md3
        operator.get_rna_type()
        return operator
    except (AttributeError, KeyError, RuntimeError):
        return None


def _import_md3_objects(operator, filepath: Path):
    existing_objects = {obj.as_pointer() for obj in bpy.data.objects}
    result = operator(filepath=str(filepath), import_tags=True)
    imported_objects = [
        obj
        for obj in bpy.data.objects
        if obj.as_pointer() not in existing_objects
    ]
    return result, imported_objects


def _imported_animation_end_frame(objects) -> int | None:
    end_frame = None
    for obj in objects:
        animation_data = getattr(obj, "animation_data", None)
        if animation_data is not None and animation_data.action is not None:
            action_end = animation_data.action.frame_range[1]
            end_frame = (
                action_end if end_frame is None else max(end_frame, action_end)
            )

        shape_keys = getattr(getattr(obj, "data", None), "shape_keys", None)
        animation_data = getattr(shape_keys, "animation_data", None)
        if animation_data is not None and animation_data.action is not None:
            action_end = animation_data.action.frame_range[1]
            end_frame = (
                action_end if end_frame is None else max(end_frame, action_end)
            )

    return None if end_frame is None else ceil(end_frame)


def _find_imported_object(objects, name: str, object_type: str):
    return next(
        (
            obj
            for obj in objects
            if obj.type == object_type
            and (obj.name == name or obj.name.startswith(name + "."))
        ),
        None,
    )


def _parent_keep_world(child, parent) -> None:
    world_matrix = child.matrix_world.copy()
    child.parent = parent
    child.matrix_world = world_matrix


def _mark_weapon_md3_objects(
    gun_objects,
    hand_objects,
    gun_rel_path: Path,
    barrel_objects=None,
    barrel_rel_path: Path | None = None,
) -> None:
    gun_mesh_name = gun_rel_path.with_suffix("").as_posix()
    gun_mesh = _find_imported_object(gun_objects, gun_mesh_name, "MESH")
    tag_flash = _find_imported_object(gun_objects, "tag_flash", "EMPTY")
    tag_weapon = _find_imported_object(gun_objects, "tag_weapon", "EMPTY")
    hand_tag_weapon = _find_imported_object(hand_objects, "tag_weapon", "EMPTY")
    missing = [
        name
        for name, obj in (
            (gun_mesh_name, gun_mesh),
            ("tag_flash", tag_flash),
            ("tag_weapon", tag_weapon),
            ("hand tag_weapon", hand_tag_weapon),
        )
        if obj is None
    ]
    if missing:
        raise RuntimeError(
            f"Weapon MD3 import did not create required object(s): {', '.join(missing)}"
        )

    model_path = normalize_rel(gun_rel_path)
    for obj in gun_objects + hand_objects + (barrel_objects or []):
        obj["_ja_weapon_md3_path"] = model_path
        obj["_ja_weapon_md3_role"] = "weapon_auxiliary"

    for obj, role in (
        (gun_mesh, "gun_mesh"),
        (tag_flash, "tag_flash"),
        (tag_weapon, "gun_tag_weapon"),
        (hand_tag_weapon, "hand_tag_weapon"),
    ):
        obj["_ja_weapon_md3_path"] = model_path
        obj["_ja_weapon_md3_role"] = role
    hand_tag_flash = _find_imported_object(hand_objects, "tag_flash", "EMPTY")
    if hand_tag_flash is not None:
        hand_tag_flash["_ja_weapon_md3_path"] = model_path
        hand_tag_flash["_ja_weapon_md3_role"] = "hand_tag_flash"
    if barrel_objects and barrel_rel_path is not None:
        barrel_mesh = _find_imported_object(
            barrel_objects,
            barrel_rel_path.with_suffix("").as_posix(),
            "MESH",
        )
        barrel_tag = _find_imported_object(barrel_objects, "tag_barrel", "EMPTY")
        weapon_tag_barrel = _find_imported_object(gun_objects, "tag_barrel", "EMPTY")
        for obj, role in (
            (barrel_mesh, "barrel_mesh"),
            (barrel_tag, "barrel_tag"),
            (weapon_tag_barrel, "gun_tag_barrel"),
        ):
            if obj is not None:
                obj["_ja_weapon_md3_path"] = model_path
                obj["_ja_weapon_md3_role"] = role


def _configure_weapon_md3_objects(objects, gun_rel_path: Path) -> None:
    model_path = normalize_rel(gun_rel_path)

    def role_object(role: str, object_type: str):
        return next(
            (
                obj
                for obj in objects
                if obj.type == object_type
                and obj.get("_ja_weapon_md3_path") == model_path
                and obj.get("_ja_weapon_md3_role") == role
            ),
            None,
        )

    gun_mesh = role_object("gun_mesh", "MESH")
    tag_flash = role_object("tag_flash", "EMPTY")
    tag_weapon = role_object("gun_tag_weapon", "EMPTY")
    hand_tag_weapon = role_object("hand_tag_weapon", "EMPTY")
    missing = [
        name
        for name, obj in (
            ("gun mesh", gun_mesh),
            ("tag_flash", tag_flash),
            ("tag_weapon", tag_weapon),
            ("hand tag_weapon", hand_tag_weapon),
        )
        if obj is None
    ]
    if missing:
        raise RuntimeError(
            f"Import the weapon and hand MD3s before setup; missing: {', '.join(missing)}"
        )

    _parent_keep_world(tag_flash, gun_mesh)
    _parent_keep_world(gun_mesh, tag_weapon)
    constraint = next(
        (
            item
            for item in tag_weapon.constraints
            if item.type == "COPY_TRANSFORMS"
            and item.name == "Weapon Hand Copy Transforms"
        ),
        None,
    )
    if constraint is None:
        constraint = tag_weapon.constraints.new(type="COPY_TRANSFORMS")
    constraint.name = "Weapon Hand Copy Transforms"
    constraint.target = hand_tag_weapon

    barrel_mesh = role_object("barrel_mesh", "MESH")
    if barrel_mesh is not None:
        barrel_tag = role_object("barrel_tag", "EMPTY")
        weapon_tag_barrel = role_object("gun_tag_barrel", "EMPTY")
        if barrel_tag is None:
            barrel_tag = next(
                (
                    obj
                    for obj in objects
                    if obj.type == "EMPTY"
                    and obj.name.startswith("tag_barrel.")
                    and obj.get("_ja_weapon_md3_path") in (None, model_path)
                ),
                None,
            )
        if weapon_tag_barrel is None:
            weapon_tag_barrel = next(
                (
                    obj
                    for obj in objects
                    if obj.type == "EMPTY"
                    and obj.name == "tag_barrel"
                    and obj.get("_ja_weapon_md3_path") in (None, model_path)
                ),
                None,
            )
        if barrel_tag is None or weapon_tag_barrel is None:
            raise RuntimeError(
                "Could not find the barrel tag_barrel.001 and gun tag_barrel"
            )
        _parent_keep_world(barrel_mesh, barrel_tag)
        barrel_constraint = next(
            (
                item
                for item in barrel_tag.constraints
                if item.type == "COPY_TRANSFORMS"
                and item.name == "Weapon Barrel Copy Transforms"
            ),
            None,
        )
        if barrel_constraint is None:
            barrel_constraint = barrel_tag.constraints.new(type="COPY_TRANSFORMS")
        barrel_constraint.name = "Weapon Barrel Copy Transforms"
        barrel_constraint.target = weapon_tag_barrel


def _configure_weapon_camera(context) -> bpy.types.Object:
    camera = bpy.data.objects.get("Weapon Preview Camera")
    if camera is None or camera.type != "CAMERA":
        camera_data = bpy.data.cameras.new("Weapon Preview Camera")
        camera = bpy.data.objects.new("Weapon Preview Camera", camera_data)
        context.scene.collection.objects.link(camera)

    camera.location = (0.0, 0.0, 0.0)
    camera.rotation_mode = "XYZ"
    camera.rotation_euler = (radians(90), 0.0, radians(270))
    camera.data.lens_unit = "FOV"
    camera.data.angle = radians(80)
    camera.data.shift_y = -0.1
    context.scene.camera = camera
    return camera


def _weapon_texture_assets(index: dict, model_entry: dict):
    folder_key = normalize_rel(Path(model_entry["rel_path"]).parent)
    sources_by_path = {}
    for source in index["textures_by_dir"].get(folder_key, []):
        key = normalize_rel(source.rel_path)
        sources_by_path.setdefault(key, []).append(source)

    assets = []
    for sources in sources_by_path.values():
        preferred = next(
            (
                source
                for source in sources
                if source.origin == model_entry["origin"]
                and source.container == model_entry["container"]
            ),
            None,
        )
        if preferred is None:
            preferred = next(
                (source for source in sources if source.origin == "disk"),
                sources[0],
            )
        assets.append((preferred, preferred.rel_path))
    return assets


def _load_weapon_textures(objects, texture_map: dict):
    failed = []
    for obj in objects:
        for slot in obj.material_slots:
            material = slot.material
            if material is None:
                continue
            shader_name = material.name.replace("\\", "/").rsplit("/", 1)[-1]
            shader_stem = Path(shader_name).stem.lower().split(".", 1)[0]
            texture_path = texture_map.get(shader_stem)
            if texture_path is None and len(texture_map) == 1:
                texture_path = next(iter(texture_map.values()))
            if texture_path is None:
                continue

            try:
                image = load_texture(texture_path, check_existing=True)
            except Exception as exc:  # noqa: BLE001
                failed.append(f"{texture_path}: {exc}")
                continue

            material.use_nodes = True
            nodes = material.node_tree.nodes
            image_node = next(
                (node for node in nodes if node.type == "TEX_IMAGE"),
                None,
            )
            if image_node is None:
                image_node = nodes.new("ShaderNodeTexImage")
                image_node.location = (-400, 200)
            image_node.image = image

            principled = next(
                (node for node in nodes if node.type == "BSDF_PRINCIPLED"),
                None,
            )
            if principled is not None and not any(
                link.to_node == principled
                and link.to_socket == principled.inputs["Base Color"]
                for link in material.node_tree.links
            ):
                material.node_tree.links.new(
                    principled.inputs["Base Color"],
                    image_node.outputs["Color"],
                )
    return failed


def _assign_material_texture(material, image) -> None:
    material.use_nodes = True
    nodes = material.node_tree.nodes
    image_nodes = [node for node in nodes if node.type == "TEX_IMAGE"]
    if not image_nodes:
        image_node = nodes.new("ShaderNodeTexImage")
        image_node.location = (-400, 200)
        image_nodes.append(image_node)
    for image_node in image_nodes:
        image_node.image = image

    principled = next(
        (node for node in nodes if node.type == "BSDF_PRINCIPLED"),
        None,
    )
    if principled is not None:
        base_color = principled.inputs["Base Color"]
        for link in list(material.node_tree.links):
            if link.to_node == principled and link.to_socket == base_color:
                material.node_tree.links.remove(link)
        material.node_tree.links.new(
            base_color,
            image_nodes[0].outputs["Color"],
        )


def _format_missing_textures(missing: list[str]) -> str:
    unique_missing = list(dict.fromkeys(missing))
    return f"Missing textures ({len(missing)}): {', '.join(unique_missing)}"


def _apply_skin_to_scene(
    scene,
    index: dict,
    base_dir: Path,
    model_name: str,
    skin_rel: Path,
    cache_root: Path,
    objects=None,
):
    entry = index["models"][model_name]
    primary = entry["primary"]
    skin_source = find_skin_source(entry, skin_rel)
    if skin_source is None:
        raise ValueError(f"Skin file not found: {skin_rel}")
    skin_map = parse_skin_text(read_text_from_source(skin_source, base_dir))
    texture_paths = {}
    missing = []
    for part_name, texture_name in skin_map.items():
        if is_skin_off(texture_name):
            continue
        resolved = resolve_texture(index, texture_name, primary)
        if resolved is None:
            missing.append(texture_name)
            continue
        _, texture_rel = resolved
        texture_paths[part_name.strip().casefold()] = cache_root / texture_rel

    skin_entries = {
        part_name.strip().casefold(): texture_name
        for part_name, texture_name in skin_map.items()
    }
    matched = 0
    failed = []
    target_objects = objects if objects is not None else scene.objects
    for obj in target_objects:
        if obj.type != "MESH":
            continue
        if "g2_configured" not in obj and "g2_prop_name" not in obj:
            continue
        part_name = obj.g2_prop.name.strip().casefold()
        texture_name = skin_entries.get(part_name)
        if texture_name is None:
            continue
        is_off = is_skin_off(texture_name)
        obj.hide_set(is_off)
        obj.hide_render = is_off
        matched += 1
        if is_off:
            continue
        texture_path = texture_paths.get(part_name)
        if texture_path is None:
            continue
        if not texture_path.is_file():
            failed.append(f"{obj.name}: cached texture missing: {texture_path}")
            continue
        try:
            image = load_texture(texture_path, check_existing=True)
        except Exception as exc:  # noqa: BLE001
            failed.append(f"{obj.name}: {texture_path}: {exc}")
            continue
        for slot in obj.material_slots:
            if slot.material is not None:
                _assign_material_texture(slot.material, image)
    return matched, missing, failed


class PK3_OT_refresh_models(Operator):
    bl_idname = "pk3.refresh_models"
    bl_label = "Refresh Models"

    def execute(self, context):
        clear_index()
        refresh_model_list(context)
        return {"FINISHED"}


class PK3_OT_import_model(Operator):
    bl_idname = "pk3.import_model"
    bl_label = "Import Model"
    import_companions: BoolProperty(default=True, options={"HIDDEN"}) # pyright: ignore[reportInvalidTypeForm]

    def execute(self, context):
        if hasattr(bpy.types.Action, "curves") and not hasattr(bpy.types.Action, "fcurves"):
            bpy.types.Action.fcurves = property(lambda self: self.curves)

        props = context.scene.glm_md3_extension
        base_dir = get_base_dir(props.game_path)
        if not base_dir.is_dir():
            self.report({"ERROR"}, "Game path is invalid")
            return {"CANCELLED"}
        index = ensure_index(base_dir)
        if not index:
            self.report({"ERROR"}, "No models found")
            return {"CANCELLED"}
        item = get_selected_model_item(props)
        if not item:
            self.report({"ERROR"}, "Select a model first")
            return {"CANCELLED"}
        if props.model_type == "weapons2" and item.file_format == "glm":
            entry = index["category_models"]["weapons2"].get(item.name)
            if not entry:
                self.report({"ERROR"}, "Selected weapon GLM is no longer indexed")
                return {"CANCELLED"}
            try:
                filepath = _materialize_model_file(base_dir, entry)
                if not filepath.is_file():
                    self.report({"ERROR"}, f"GLM file not found: {filepath}")
                    return {"CANCELLED"}
                cache_root = base_dir / CACHE_FOLDER
                clear_cached_textures(cache_root)
                texture_map, failed = extract_assets(
                    base_dir,
                    cache_root,
                    _weapon_texture_assets(index, entry),
                    clean_stale=False,
                )
                basepath = (
                    base_dir / CACHE_FOLDER
                    if entry["origin"] == "pk3"
                    else base_dir
                )
                result = bpy.ops.import_scene.glm(
                    filepath=str(filepath),
                    skin="",
                    basepath=str(basepath),
                    guessTextures=False,
                )
                relink_images_from_cache(texture_map)
            except Exception as exc:  # noqa: BLE001
                self.report({"ERROR"}, f"Weapon GLM import failed: {exc}")
                return {"CANCELLED"}
            if "FINISHED" not in result:
                self.report({"ERROR"}, "Weapon GLM importer did not finish")
                return {"CANCELLED"}
            if failed:
                self.report(
                    {"WARNING"},
                    f"Failed to extract weapon textures: {', '.join(failed)}",
                )
            return {"FINISHED"}
        if item.file_format == "md3":
            operator = _get_md3_operator()
            if operator is None:
                self.report(
                    {"ERROR"},
                    "MD3 import requires the Import id Tech 3 BSP add-on to be enabled",
                )
                return {"CANCELLED"}
            entry = index["category_models"].get(props.model_type, {}).get(item.name)
            if not entry:
                self.report({"ERROR"}, "Selected MD3 file is no longer indexed")
                return {"CANCELLED"}
            preferences = None
            previous_base_path = None
            try:
                filepath = _materialize_model_file(base_dir, entry)
                if not filepath.is_file():
                    self.report({"ERROR"}, f"MD3 file not found: {filepath}")
                    return {"CANCELLED"}
                texture_assets = (
                    _weapon_texture_assets(index, entry)
                    if props.model_type == "weapons2"
                    else []
                )
                cache_root = base_dir / CACHE_FOLDER
                clear_cached_textures(cache_root)
                texture_map, failed_textures = extract_assets(
                    base_dir,
                    cache_root,
                    texture_assets,
                    clean_stale=False,
                )
                existing_objects = {obj.as_pointer() for obj in bpy.data.objects}
                addon = context.preferences.addons.get("import_bsp")
                if addon and addon.preferences is not None:
                    preferences = addon.preferences
                    previous_base_path = preferences.base_path
                    preferences.base_path = str(base_dir)
                if props.model_type == "weapons2" and self.import_companions:
                    weapon_entries = [entry]
                    weapon_parts = []
                    for weapon_entry in weapon_entries:
                        gun_rel_path = Path(weapon_entry["rel_path"])
                        numbered_match = re.fullmatch(
                            r"(.+)_([0-9]+)",
                            gun_rel_path.stem,
                        )
                        companion_stem = (
                            numbered_match.group(1)
                            if numbered_match is not None
                            else gun_rel_path.stem
                        )
                        hand_rel_path = gun_rel_path.with_name(
                            f"{companion_stem}_hand.md3"
                        )
                        hand_entry = index["category_models"]["weapons2"].get(
                            normalize_rel(hand_rel_path)
                        )
                        if hand_entry is None:
                            raise FileNotFoundError(
                                f"Matching weapon hand MD3 not found: {hand_rel_path}"
                            )
                        numbered_barrel_rel_path = gun_rel_path.with_name(
                            f"{gun_rel_path.stem}_barrel.md3"
                        )
                        barrel_entry = index["category_models"]["weapons2"].get(
                            normalize_rel(numbered_barrel_rel_path)
                        )
                        barrel_rel_path = numbered_barrel_rel_path
                        if barrel_entry is None and numbered_match is not None:
                            barrel_rel_path = gun_rel_path.with_name(
                                f"{companion_stem}_barrel.md3"
                            )
                            barrel_entry = index["category_models"]["weapons2"].get(
                                normalize_rel(barrel_rel_path)
                            )
                        weapon_parts.append(
                            (
                                weapon_entry,
                                hand_entry,
                                hand_rel_path,
                                barrel_entry,
                                barrel_rel_path,
                            )
                        )

                    imported_objects = []
                    for (
                        weapon_entry,
                        hand_entry,
                        hand_rel_path,
                        barrel_entry,
                        barrel_rel_path,
                    ) in weapon_parts:
                        gun_rel_path = Path(weapon_entry["rel_path"])
                        gun_filepath = _materialize_model_file(
                            base_dir,
                            weapon_entry,
                        )
                        gun_result, gun_objects = _import_md3_objects(
                            operator,
                            gun_filepath,
                        )
                        if "FINISHED" not in gun_result:
                            raise RuntimeError("Gun MD3 importer did not finish")

                        hand_filepath = _materialize_model_file(base_dir, hand_entry)
                        hand_result, hand_objects = _import_md3_objects(
                            operator,
                            hand_filepath,
                        )
                        if "FINISHED" not in hand_result:
                            raise RuntimeError(
                                f"Weapon hand MD3 importer did not finish: {hand_rel_path}"
                            )

                        barrel_objects = []
                        if barrel_entry is not None:
                            barrel_filepath = _materialize_model_file(
                                base_dir,
                                barrel_entry,
                            )
                            barrel_result, barrel_objects = _import_md3_objects(
                                operator,
                                barrel_filepath,
                            )
                            if "FINISHED" not in barrel_result:
                                raise RuntimeError(
                                    f"Weapon barrel MD3 importer did not finish: {barrel_rel_path}"
                                )

                        _mark_weapon_md3_objects(
                            gun_objects,
                            hand_objects,
                            gun_rel_path,
                            barrel_objects,
                            barrel_rel_path if barrel_objects else None,
                        )
                        imported_objects.extend(
                            gun_objects + hand_objects + barrel_objects
                        )
                        result = hand_result
                elif props.model_type == "weapons2":
                    result, imported_objects = _import_md3_objects(
                        operator,
                        filepath,
                    )
                else:
                    result = operator(filepath=str(filepath))
                    imported_objects = [
                        obj
                        for obj in bpy.data.objects
                        if obj.as_pointer() not in existing_objects
                    ]
                failed_textures.extend(
                    _load_weapon_textures(imported_objects, texture_map)
                )
            except Exception as exc:  # noqa: BLE001
                self.report({"ERROR"}, f"MD3 import failed: {exc}")
                return {"CANCELLED"}
            finally:
                if preferences is not None:
                    preferences.base_path = previous_base_path
            if "FINISHED" not in result:
                self.report({"ERROR"}, "MD3 importer did not finish")
                return {"CANCELLED"}
            animation_end_frame = _imported_animation_end_frame(imported_objects)
            if animation_end_frame is not None:
                context.scene.frame_end = max(
                    context.scene.frame_start,
                    animation_end_frame,
                )
            if failed_textures:
                self.report(
                    {"WARNING"},
                    f"Failed to load weapon texture(s): {', '.join(failed_textures)}",
                )
            return {"FINISHED"}
        if props.model_type != "players":
            self.report({"ERROR"}, "Only player GLM import is supported")
            return {"CANCELLED"}
        model_name = get_selected_model_from_props(props)
        if not model_name:
            self.report({"ERROR"}, "Select a model first")
            return {"CANCELLED"}
        ensure_skin_selected(props)
        if not props.skin_name:
            self.report({"ERROR"}, "Select a skin file before import")
            return {"CANCELLED"}
        skin_rel = Path(props.skin_name)
        try:
            assets, missing, replacements = collect_assets_for_skin(
                index,
                base_dir,
                model_name,
                skin_rel,
            )
        except Exception as exc:  # noqa: BLE001
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        cache_root = base_dir / CACHE_FOLDER
        try:
            clear_cached_textures(cache_root)
            texture_map, failed = extract_assets(base_dir, cache_root, assets)
        except Exception as exc:  # noqa: BLE001
            self.report({"ERROR"}, f"Failed to prepare model textures: {exc}")
            return {"CANCELLED"}
        rewrite_skin_paths(cache_root, skin_rel, replacements)
        glm_dest = cache_root / assets[0][1]
        skin_suffix = derive_skin_suffix(skin_rel)
        existing_objects = {obj.as_pointer() for obj in bpy.data.objects}
        try:
            bpy.ops.import_scene.glm(
                filepath=str(glm_dest),
                skin=skin_suffix,
                basepath=str(cache_root),
                guessTextures=False,
            )
        except Exception as exc:  # noqa: BLE001
            self.report({"ERROR"}, f"Import failed: {exc}")
            return {"CANCELLED"}
        relink_images_from_cache(texture_map)
        imported_objects = [
            obj
            for obj in bpy.data.objects
            if obj.as_pointer() not in existing_objects
        ]
        try:
            _, _, failed_to_apply = _apply_skin_to_scene(
                context.scene,
                index,
                base_dir,
                model_name,
                skin_rel,
                cache_root,
                objects=imported_objects,
            )
        except Exception as exc:  # noqa: BLE001
            self.report({"ERROR"}, f"Failed to apply imported skin: {exc}")
            return {"CANCELLED"}
        if missing:
            self.report({"WARNING"}, _format_missing_textures(missing))
        if failed:
            self.report({"WARNING"}, f"Failed to extract: {', '.join(failed)}")
        if failed_to_apply:
            self.report(
                {"WARNING"},
                f"Failed to apply skin texture(s): {', '.join(failed_to_apply)}",
            )
        return {"FINISHED"}


class PK3_OT_apply_skin(Operator):
    bl_idname = "pk3.apply_skin"
    bl_label = "Apply Skin Textures"

    def execute(self, context):
        props = context.scene.glm_md3_extension
        base_dir = get_base_dir(props.game_path)
        if not base_dir.is_dir():
            self.report({"ERROR"}, "Game path is invalid")
            return {"CANCELLED"}
        index = ensure_index(base_dir)
        if props.model_type != "players":
            self.report({"ERROR"}, "Skin application is only supported for player models")
            return {"CANCELLED"}
        model_name = get_selected_model_from_props(props)
        if not index or not model_name:
            self.report({"ERROR"}, "Select a model first")
            return {"CANCELLED"}
        ensure_skin_selected(props)
        if not props.skin_name:
            self.report({"ERROR"}, "Select a skin file")
            return {"CANCELLED"}
        skin_rel = Path(props.skin_name)
        try:
            assets, missing, replacements = collect_assets_for_skin(index, base_dir, model_name, skin_rel)
        except Exception as exc:  # noqa: BLE001
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        cache_root = base_dir / CACHE_FOLDER
        try:
            clear_cached_textures(cache_root)
            _, failed = extract_assets(base_dir, cache_root, assets)
        except Exception as exc:  # noqa: BLE001
            self.report({"ERROR"}, f"Failed to prepare skin textures: {exc}")
            return {"CANCELLED"}
        rewrite_skin_paths(cache_root, skin_rel, replacements)
        try:
            applied, skin_missing, failed_to_apply = _apply_skin_to_scene(
                context.scene,
                index,
                base_dir,
                model_name,
                skin_rel,
                cache_root,
            )
        except Exception as exc:  # noqa: BLE001
            self.report({"ERROR"}, f"Failed to apply skin: {exc}")
            return {"CANCELLED"}
        if applied == 0:
            self.report(
                {"WARNING"},
                "No scene objects matched the selected skin's g2_prop.name entries",
            )
        if skin_missing:
            missing.extend(skin_missing)
        if missing:
            self.report({"WARNING"}, _format_missing_textures(missing))
        if failed:
            self.report({"WARNING"}, f"Failed to extract: {', '.join(failed)}")
        if failed_to_apply:
            self.report(
                {"WARNING"},
                f"Failed to apply skin texture(s): {', '.join(failed_to_apply)}",
            )
        return {"FINISHED"}


class PK3_OT_extract_model(Operator):
    bl_idname = "pk3.extract_model"
    bl_label = "Extract Model"

    def execute(self, context):
        props = context.scene.glm_md3_extension
        base_dir = get_base_dir(props.game_path)
        if not base_dir.is_dir():
            self.report({"ERROR"}, "Game path is invalid")
            return {"CANCELLED"}
        if not props.model_extract_dir:
            self.report({"ERROR"}, "Select an extraction folder")
            return {"CANCELLED"}
        item = get_selected_model_item(props)
        if item is None:
            self.report({"ERROR"}, "Select a model first")
            return {"CANCELLED"}

        index = ensure_index(base_dir)
        if not index:
            self.report({"ERROR"}, "No models found")
            return {"CANCELLED"}
        if props.model_type == "players":
            model_entry = index["models"].get(item.name)
            if not model_entry:
                self.report({"ERROR"}, "Selected player model is no longer indexed")
                return {"CANCELLED"}
            primary = model_entry["primary"]
            folder_rel = primary.glm.parent
            origin = primary.origin
            container = primary.container
        else:
            model_entry = index["category_models"].get(props.model_type, {}).get(item.name)
            if not model_entry:
                self.report({"ERROR"}, "Selected model is no longer indexed")
                return {"CANCELLED"}
            folder_rel = Path(model_entry["rel_path"]).parent
            origin = model_entry["origin"]
            container = model_entry["container"]

        try:
            output_dir = Path(props.model_extract_dir).expanduser()
            output_dir.mkdir(parents=True, exist_ok=True)

            # AANPASSING: destination_rel gebruikt nu altijd Path(folder_rel.name)
            copied = _extract_model_folder(
                base_dir,
                folder_rel,
                origin,
                container,
                output_dir,
                destination_rel=Path(folder_rel.name),
            )

            unresolved_models = []
            if props.model_type == "players":
                for referenced_name in sorted(
                    _referenced_player_model_names(model_entry, base_dir),
                    key=str.casefold,
                ):
                    if referenced_name.casefold() == item.name.casefold():
                        continue
                    folder_source = _player_model_folder_source(
                        base_dir,
                        referenced_name,
                    )
                    if folder_source is None:
                        unresolved_models.append(referenced_name)
                        continue
                    extra_folder, extra_origin, extra_container = folder_source
                    copied += _extract_model_folder(
                        base_dir,
                        extra_folder,
                        extra_origin,
                        extra_container,
                        output_dir,
                        destination_rel=Path(extra_folder.name),
                    )
        except Exception as exc:  # noqa: BLE001
            self.report({"ERROR"}, f"Model extraction failed: {exc}")
            return {"CANCELLED"}

        self.report({"INFO"}, f"Extracted {copied} file(s) to {output_dir}")
        if unresolved_models:
            self.report(
                {"WARNING"},
                f"Could not find referenced player model folder(s): {', '.join(unresolved_models)}",
            )
        return {"FINISHED"}


class PK3_OT_prepare_modview(Operator):
    bl_idname = "pk3.prepare_modview"
    bl_label = "Prepare ModView Directory"

    def execute(self, context):
        base_dir = get_base_dir(context.scene.glm_md3_extension.game_path)
        if not base_dir.is_dir():
            self.report({"ERROR"}, "Game path is invalid")
            return {"CANCELLED"}
        try:
            destination, copied, archive_failures = _prepare_modview_directory(base_dir)
        except Exception as exc:  # noqa: BLE001
            self.report({"ERROR"}, f"Failed to prepare ModView directory: {exc}")
            return {"CANCELLED"}
        self.report(
            {"INFO"},
            f"Prepared {destination} with {copied} _humanoid file(s)",
        )
        if archive_failures:
            self.report(
                {"WARNING"},
                f"Could not read PK3 archive(s): {', '.join(archive_failures)}",
            )
        return {"FINISHED"}


class PK3_OT_setup_weapon_preview(Operator):
    bl_idname = "pk3.setup_weapon_preview"
    bl_label = "Setup Weapon Preview"

    def execute(self, context):
        props = context.scene.glm_md3_extension
        if props.model_type != "weapons2":
            self.report({"ERROR"}, "Weapon setup is only available for weapons2")
            return {"CANCELLED"}
        item = get_selected_model_item(props)
        if item is None or item.file_format != "md3":
            self.report({"ERROR"}, "Select a weapons2 MD3 model first")
            return {"CANCELLED"}
        try:
            _configure_weapon_md3_objects(
                context.scene.objects,
                Path(item.name),
            )
            _configure_weapon_camera(context)
        except Exception as exc:  # noqa: BLE001
            self.report({"ERROR"}, f"Failed to set up weapon preview: {exc}")
            return {"CANCELLED"}
        self.report({"INFO"}, "Weapon preview hierarchy and camera are ready")
        return {"FINISHED"}


class PK3_OT_remove_camera_invisible_faces(Operator):
    bl_idname = "pk3.remove_camera_invisible_faces"
    bl_label = "Remove Camera-Invisible Faces"
    bl_options = {"REGISTER", "UNDO"}
    bl_description = (
        "Delete faces of the active mesh not hit by a pixel ray from the "
        "camera-view viewport"
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "MESH"

    def invoke(self, context, _event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, _context):
        layout = self.layout
        layout.label(text="This removes faces from the active mesh (undoable).")
        layout.label(text="Blender may freeze briefly while scanning the mesh.")

    def execute(self, context):
        obj = context.active_object
        if not _is_camera_view(context):
            self.report({"ERROR"}, "Switch to the active camera view with Numpad 0 first")
            return {"CANCELLED"}
        camera = context.scene.camera
        if camera is None or camera.type != "CAMERA":
            self.report({"ERROR"}, "Set an active scene camera first")
            return {"CANCELLED"}
        if camera.data.type not in {"PERSP", "ORTHO"}:
            self.report({"ERROR"}, "Only perspective and orthographic cameras are supported")
            return {"CANCELLED"}
        if obj.mode != "OBJECT":
            self.report({"ERROR"}, "Switch the active mesh to Object Mode first")
            return {"CANCELLED"}
        if obj.modifiers:
            self.report(
                {"ERROR"},
                "Apply or remove the active mesh's modifiers before pruning faces",
            )
            return {"CANCELLED"}
        if not obj.data.polygons:
            self.report({"WARNING"}, "The active mesh has no faces")
            return {"CANCELLED"}

        try:
            region = next(
                (region for region in context.area.regions if region.type == "WINDOW"),
                None,
            )
            if region is None:
                self.report({"ERROR"}, "Could not find the 3D View window region")
                return {"CANCELLED"}
            region_3d = context.space_data.region_3d
            depsgraph = context.evaluated_depsgraph_get()
            visible_faces = set()
            for pixel_y in range(region.height):
                for pixel_x in range(region.width):
                    coordinate = Vector((pixel_x + 0.5, pixel_y + 0.5))
                    ray_origin = view3d_utils.region_2d_to_origin_3d(
                        region,
                        region_3d,
                        coordinate,
                        clamp=camera.data.clip_end,
                    )
                    ray_direction = view3d_utils.region_2d_to_vector_3d(
                        region,
                        region_3d,
                        coordinate,
                    )
                    hit, _, _, face_index, hit_obj, _ = context.scene.ray_cast(
                        depsgraph,
                        ray_origin,
                        ray_direction,
                        distance=camera.data.clip_end,
                    )
                    if hit and getattr(hit_obj, "original", hit_obj) == obj:
                        visible_faces.add(face_index)
        except Exception as exc:
            self.report({"ERROR"}, f"Camera visibility scan failed: {exc}")
            return {"CANCELLED"}

        mesh = obj.data
        bm = bmesh.new()
        try:
            bm.from_mesh(mesh)
            bm.faces.ensure_lookup_table()
            bm.faces.index_update()
            faces_to_remove = [
                face for face in bm.faces if face.index not in visible_faces
            ]
            removed_count = len(faces_to_remove)
            if removed_count:
                bmesh.ops.delete(bm, geom=faces_to_remove, context="FACES")
                bm.to_mesh(mesh)
                mesh.update()
        except Exception as exc:
            self.report({"ERROR"}, f"Could not remove invisible faces: {exc}")
            return {"CANCELLED"}
        finally:
            bm.free()

        self.report(
            {"INFO"},
            f"Removed {removed_count} face(s); kept {len(visible_faces)} "
            "camera-visible face(s)",
        )
        return {"FINISHED"}


class PK3_OT_prepare_weapon_export(Operator):
    bl_idname = "pk3.prepare_weapon_export"
    bl_label = "Prepare for Export"
    keep_component: EnumProperty(
        items=(
            ("WEAPON", "Keep Weapon", "Keep the weapon mesh and its tags"),
            ("BARREL", "Keep Barrel", "Keep the barrel mesh and its tag"),
        ),
        options={"HIDDEN"},
    ) # pyright: ignore[reportInvalidTypeForm]

    def execute(self, context):
        props = context.scene.glm_md3_extension
        if props.model_type != "weapons2":
            self.report({"ERROR"}, "Export preparation is only available for weapons2")
            return {"CANCELLED"}
        item = get_selected_model_item(props)
        if item is None or item.file_format != "md3":
            self.report({"ERROR"}, "Select a weapons2 MD3 model first")
            return {"CANCELLED"}

        model_path = normalize_rel(Path(item.name))
        weapon_objects = [
            obj
            for obj in context.scene.objects
            if obj.get("_ja_weapon_md3_path") == model_path
        ]
        if not weapon_objects:
            self.report(
                {"ERROR"},
                "Import the selected weapon MD3 before export preparation",
            )
            return {"CANCELLED"}

        def find_role(role: str):
            return next(
                (
                    obj
                    for obj in weapon_objects
                    if obj.get("_ja_weapon_md3_role") == role
                ),
                None,
            )

        barrel_mesh = find_role("barrel_mesh")
        barrel_tag = find_role("barrel_tag")
        if self.keep_component == "BARREL" and (
            barrel_mesh is None or barrel_tag is None
        ):
            self.report(
                {"ERROR"},
                "The imported weapon has no barrel mesh and tag to keep",
            )
            return {"CANCELLED"}

        delete_roles = (
            {
                "gun_mesh",
                "tag_flash",
                "gun_tag_weapon",
                "gun_tag_barrel",
                "hand_tag_weapon",
                "hand_tag_flash",
                "weapon_auxiliary",
            }
            if self.keep_component == "BARREL"
            else {
                "barrel_mesh",
                "barrel_tag",
                "hand_tag_weapon",
                "hand_tag_flash",
                "weapon_auxiliary",
            }
        )
        objects_to_delete = [
            obj
            for obj in weapon_objects
            if obj.get("_ja_weapon_md3_role") in delete_roles
        ]

        weapon_tag = find_role("gun_tag_weapon")
        hand_tag = find_role("hand_tag_weapon")
        tags_to_clean = [(weapon_tag, "Weapon Hand Copy Transforms", hand_tag)]
        if self.keep_component == "BARREL":
            tags_to_clean.append(
                (barrel_tag, "Weapon Barrel Copy Transforms", find_role("gun_tag_barrel"))
            )
        for tag, constraint_name, target in tags_to_clean:
            if tag is None:
                continue
            for constraint in list(tag.constraints):
                if constraint.type == "COPY_TRANSFORMS" and (
                    constraint.name == constraint_name
                    or (target is not None and constraint.target == target)
                ):
                    tag.constraints.remove(constraint)

        deleted_objects = 0
        for obj in objects_to_delete:
            if obj.name in context.scene.objects:
                bpy.data.objects.remove(obj, do_unlink=True)
                deleted_objects += 1

        if self.keep_component == "BARREL":
            barrel_tag.name = "tag_barrel"
        camera = bpy.data.objects.get("Weapon Preview Camera")
        if camera is not None and camera.type == "CAMERA":
            camera_data = camera.data
            if context.scene.camera == camera:
                context.scene.camera = None
            bpy.data.objects.remove(camera, do_unlink=True)
            if camera_data.users == 0:
                bpy.data.cameras.remove(camera_data)
        self.report(
            {"INFO"},
            f"Prepared for export: kept the {self.keep_component.lower()} and "
            f"deleted {deleted_objects} object(s)",
        )
        return {"FINISHED"}
