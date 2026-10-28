from __future__ import annotations

bl_info = {
    "name": "GLM/MD3 Extension",
    "author": "Maui",
    "version": (0, 5, 6),
    "blender": (5, 2, 0),
    "location": "View3D > Sidebar > PK3",
    "description": "Browse PK3 files, import/extract md3/glm from assets, Weapon Modding tools.",
    "category": "Import-Export Extension",
}

# All functionality lives in addon_impl to keep __init__ lean.
from .addon_impl import *  # noqa: F401,F403
from .addon_impl import register, unregister

__all__ = ["register", "unregister"]
