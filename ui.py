from __future__ import annotations

from bpy.types import Panel, UIList

from .operators import (
    PK3_OT_apply_skin,
    PK3_OT_extract_model,
    PK3_OT_import_model,
    PK3_OT_prepare_modview,
    PK3_OT_prepare_weapon_export,
    PK3_OT_refresh_models,
    PK3_OT_setup_weapon_preview,
)
from .index import normalize_rel
from .props import get_selected_model_item


class PK3_UL_models(UIList):
    bl_idname = "PK3_UL_models"

    def draw_item(
        self,
        context,
        layout,
        data,
        item,
        icon,
        active_data,
        active_propname,
        index,
    ):
        if item.is_header:
            layout.label(text=item.label, icon="OUTLINER_COLLECTION")
            return
        row = layout.row(align=True)
        row.label(text=item.label)
        row.label(
            text=item.source,
            icon="FILE_FOLDER" if item.source == "disk" else "FILE_ARCHIVE",
        )


class PK3_PT_panel(Panel):
    bl_idname = "PK3_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "PK3"
    bl_label = "PK3 Browser"

    def draw(self, context):
        props = context.scene.pk3_browser
        layout = self.layout
        layout.prop(props, "game_path")
        layout.prop(props, "model_type")
        row = layout.row()
        row.prop(props, "search", text="", icon="VIEWZOOM")
        row.operator(PK3_OT_refresh_models.bl_idname, text="", icon="FILE_REFRESH")

        layout.template_list(
            "PK3_UL_models",
            "",
            props,
            "model_items",
            props,
            "active_model_index",
            rows=8,
        )
        if not props.model_items:
            layout.label(text="No models found", icon="INFO")

        if props.game_path.strip():
            layout.operator(
                PK3_OT_prepare_modview.bl_idname,
                text="Prepare ModView Directory",
                icon="FILE_FOLDER",
            )

        selected_item = get_selected_model_item(props)
        if not selected_item:
            return
        if props.model_type == "players":
            layout.prop(props, "skin_name")
            row = layout.row(align=True)
            row.operator(PK3_OT_import_model.bl_idname, icon="IMPORT")
            row.operator(PK3_OT_apply_skin.bl_idname, text="Apply Skin", icon="TEXTURE")
            layout.separator()
            layout.prop(props, "model_extract_dir")
            layout.operator(PK3_OT_extract_model.bl_idname, icon="FILE_FOLDER")
        else:
            if props.model_type == "weapons2" and selected_item.file_format == "glm":
                layout.operator(
                    PK3_OT_import_model.bl_idname,
                    text="Import GLM (weapon)",
                    icon="IMPORT",
                )
            elif selected_item.file_format == "md3":
                if props.model_type == "weapons2":
                    row = layout.row(align=True)
                    row.operator(
                        PK3_OT_import_model.bl_idname,
                        text="Import Animated Weapon",
                        icon="IMPORT",
                    )
                    row.operator(
                        PK3_OT_import_model.bl_idname,
                        text="Import Selected MD3",
                        icon="IMPORT",
                    ).import_companions = False
                else:
                    layout.operator(
                        PK3_OT_import_model.bl_idname,
                        text="Import MD3",
                        icon="IMPORT",
                    )
                layout.label(
                    text="Requires SomaZ's Import id Tech 3 BSP add-on",
                    icon="INFO",
                )
                if props.model_type == "weapons2":
                    layout.operator(
                        PK3_OT_setup_weapon_preview.bl_idname,
                        text="Setup Weapon",
                        icon="CONSTRAINT",
                    )
                    layout.label(text="Prepare to Export", icon="EXPORT")
                    row = layout.row(align=True)
                    model_path = normalize_rel(selected_item.name)
                    weapon_objects = (
                        obj
                        for obj in context.scene.objects
                        if obj.get("_ja_weapon_md3_path") == model_path
                    )
                    weapon_roles = {
                        obj.get("_ja_weapon_md3_role") for obj in weapon_objects
                    }
                    barrel_button = row.row()
                    barrel_button.enabled = {
                        "barrel_mesh",
                        "barrel_tag",
                    }.issubset(weapon_roles)
                    barrel_button.operator(
                        PK3_OT_prepare_weapon_export.bl_idname,
                        text="Barrel",
                    ).keep_component = "BARREL"
                    row.operator(
                        PK3_OT_prepare_weapon_export.bl_idname,
                        text="Weapon",
                    ).keep_component = "WEAPON"
            else:
                layout.label(
                    text="Import is currently supported for player GLM models",
                    icon="INFO",
                )
            layout.separator()
            layout.prop(props, "model_extract_dir")
            layout.operator(PK3_OT_extract_model.bl_idname, icon="FILE_FOLDER")
