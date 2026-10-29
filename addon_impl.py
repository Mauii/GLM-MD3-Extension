from __future__ import annotations

# Central registration for the add-on. Implementation is split into modules for clarity.

import bpy
from bpy.props import PointerProperty

from .props import PK3BrowserProperties, PK3ModelItem
from .operators import (
    PK3_OT_apply_skin,
    PK3_OT_extract_model,
    PK3_OT_import_model,
    PK3_OT_prepare_modview,
    PK3_OT_prepare_weapon_export,
    PK3_OT_remove_camera_invisible_faces,
    PK3_OT_refresh_models,
    PK3_OT_setup_weapon_preview,
)
from .ui import PK3_PT_panel, PK3_UL_models

CLASSES = (
    PK3ModelItem,
    PK3BrowserProperties,
    PK3_OT_refresh_models,
    PK3_OT_import_model,
    PK3_OT_apply_skin,
    PK3_OT_extract_model,
    PK3_OT_prepare_modview,
    PK3_OT_prepare_weapon_export,
    PK3_OT_setup_weapon_preview,
    PK3_OT_remove_camera_invisible_faces,
    PK3_UL_models,
    PK3_PT_panel,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.glm_md3_extension = PointerProperty(type=PK3BrowserProperties)


def unregister():
    del bpy.types.Scene.glm_md3_extension
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
