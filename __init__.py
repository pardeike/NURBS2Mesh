# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025 Andreas Pardeike

# pyright: reportInvalidTypeForm=false

bl_info = {
    "name": "NURBS2Mesh",
    "author": "Andreas",
    "version": (1, 0, 1),
    "blender": (4, 2, 0),
    "location": "Object Properties > NURBS2Mesh",
    "description": "Auto-updating mesh copy from NURBS/Curve/Surface with debounce",
    "category": "Object",
}

import bpy
from mathutils import Matrix
from bpy.props import (
    BoolProperty,
    FloatProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import (
    AddonPreferences,
    Operator,
    Panel,
    PropertyGroup,
)

from .menu_injector import (
    MenuInjectionHandle,
    register_menu_item,
    unregister_menu_item,
)

from .core import (
    build_mesh_from_source,
    clear_runtime_state,
    depsgraph_update_handler,
    first_user_collection,
    forget_fingerprint,
    linked_meshes_for_source,
    load_post_handler,
    update_now_by_name,
)
### Properties

class N2M_Preferences(AddonPreferences):
    bl_idname = __name__

    default_debounce: FloatProperty(
        name="Default Debounce (s)",
        description="Delay after last edit before auto-update runs",
        min=0.0, default=0.25, subtype='TIME'
    )
    auto_parent: BoolProperty(
        name="Parent new mesh to source",
        description="Keep transforms in sync by parenting mesh copy to source",
        default=True,
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "default_debounce")
        layout.prop(self, "auto_parent")

class N2M_LinkProps(PropertyGroup):
    source: PointerProperty(
        name="Source",
        type=bpy.types.Object,
        description="Linked NURBS/Curve/Surface source object"
    )
    auto_update: BoolProperty(
        name="Auto Update",
        description="Regenerate mesh when source geometry changes",
        default=True
    )
    debounce: FloatProperty(
        name="Debounce (s)",
        description="Wait time after last change before updating",
        min=0.0, default=0.25, subtype='TIME'
    )
    apply_modifiers: BoolProperty(
        name="Apply Modifiers from Source",
        description="Include evaluated modifiers when generating mesh",
        default=True
    )
    preserve_all_data_layers: BoolProperty(
        name="Preserve All Data Layers",
        description="Ask Blender to preserve UVs, vertex groups, etc, when possible",
        default=True
    )
    note: StringProperty(
        name="Note",
        description="Optional note"
    )

### Operators

class N2M_OT_link_mesh(Operator):
    bl_idname = "n2m.link_mesh"
    bl_label = "Duplicate As Linked Mesh"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        src = context.object
        if src is None or src.type not in {'CURVE', 'SURFACE'}:
            self.report({'ERROR'}, "Select a NURBS/Curve/Surface object")
            return {'CANCELLED'}

        prefs = context.preferences.addons[__name__].preferences

        mesh = build_mesh_from_source(src)
        name_base = f"{src.name} Mesh"
        new_obj = bpy.data.objects.new(name_base, mesh)
        coll = first_user_collection(src, context)
        coll.objects.link(new_obj)

        if prefs.auto_parent:
            new_obj.parent = src
            new_obj.matrix_parent_inverse = Matrix.Identity(4)
            new_obj.matrix_basis = Matrix.Identity(4)
            new_obj.matrix_world = src.matrix_world

        link = new_obj.n2m
        link.source = src
        try:
            link.debounce = float(prefs.default_debounce)
        except Exception:
            link.debounce = 0.25
        link.auto_update = True
        link.apply_modifiers = True
        link.preserve_all_data_layers = True

        view_layer = getattr(context, 'view_layer', None)
        if view_layer:
            for obj_sel in list(context.selected_objects):
                obj_sel.select_set(False)
        new_obj.select_set(True)
        if view_layer:
            view_layer.objects.active = new_obj

        self.report({'INFO'}, f"Linked mesh created: {new_obj.name}")
        return {'FINISHED'}


class N2M_OT_update_now(Operator):
    bl_idname = "n2m.update_now"
    bl_label = "Update Now"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.object
        # If active is a mesh link, update that one; if a curve/surface, update its targets.
        if obj and obj.type == 'MESH' and getattr(obj, "n2m", None) and obj.n2m.source:
            src = obj.n2m.source
            if src and getattr(src, 'name', None):
                update_now_by_name(src.name, include_disabled=True)
            else:
                self.report({'ERROR'}, 'Linked source is missing')
                return {'CANCELLED'}
            return {'FINISHED'}
        if obj and obj.type in {'CURVE', 'SURFACE'}:
            update_now_by_name(obj.name, include_disabled=True)
            return {'FINISHED'}
        self.report({'ERROR'}, "Select a linked mesh or its NURBS/Curve/Surface source")
        return {'CANCELLED'}

class N2M_OT_unlink(Operator):
    bl_idname = "n2m.unlink"
    bl_label = "Unlink"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.object
        if obj is None or obj.type != 'MESH' or not getattr(obj, "n2m", None) or not obj.n2m.source:
            self.report({'ERROR'}, "Select a linked mesh to unlink")
            return {'CANCELLED'}
        src = obj.n2m.source
        obj.n2m.source = None
        if src and getattr(src, 'name', None):
            forget_fingerprint(src.name)
        self.report({'INFO'}, "Unlinked mesh from source")
        return {'FINISHED'}

### Panel

class N2M_PT_panel(Panel):
    bl_label = "NURBS2Mesh"
    bl_idname = "N2M_PT_panel"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "object"

    @classmethod
    def poll(cls, context):
        o = context.object
        if o is None:
            return False
        if o.type in {'CURVE', 'SURFACE'}:
            return True
        if o.type == 'MESH' and hasattr(o, "n2m"):
            return True
        return False

    def draw(self, context):
        layout = self.layout
        o = context.object
        if o.type in {'CURVE', 'SURFACE'}:
            layout.operator(N2M_OT_link_mesh.bl_idname, text="Duplicate As Linked Mesh", icon='MESH_DATA')
            layout.separator()
            targets = linked_meshes_for_source(o, include_disabled=True)
            if targets:
                col = layout.column(align=True)
                col.label(text="Linked Meshes:")
                for t in targets:
                    row = col.row(align=True)
                    row.prop(t.n2m, "auto_update", text="", icon='REC')
                    row.label(text=t.name)
                    row.operator(N2M_OT_update_now.bl_idname, text="", icon='FILE_REFRESH')
            else:
                layout.label(text="No linked meshes")

        if o.type == 'MESH' and hasattr(o, "n2m"):
            box = layout.box()
            box.prop(o.n2m, "source")
            if o.n2m.source:
                box.prop(o.n2m, "auto_update")
                box.prop(o.n2m, "debounce")
                box.prop(o.n2m, "apply_modifiers")
                box.prop(o.n2m, "preserve_all_data_layers")
                box.operator(N2M_OT_update_now.bl_idname, icon='FILE_REFRESH')
                box.operator(N2M_OT_unlink.bl_idname, icon='X')

### UI integration


def _n2m_is_link_mesh_enabled(context):
    obj = getattr(context, "object", None)
    return bool(obj and obj.type in {'CURVE', 'SURFACE'})


_OBJECT_MENU_ITEM: MenuInjectionHandle | None = None

### Register

_CLASSES = (
    N2M_Preferences,
    N2M_LinkProps,
    N2M_OT_link_mesh,
    N2M_OT_update_now,
    N2M_OT_unlink,
    N2M_PT_panel,
)

def register():
    clear_runtime_state()
    for c in _CLASSES:
        bpy.utils.register_class(c)
    bpy.types.Object.n2m = PointerProperty(type=N2M_LinkProps)
    if depsgraph_update_handler not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(depsgraph_update_handler)
    if load_post_handler not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(load_post_handler)
    global _OBJECT_MENU_ITEM
    if _OBJECT_MENU_ITEM is None:
        _OBJECT_MENU_ITEM = register_menu_item(
            menu="VIEW3D_MT_object",
            operator=N2M_OT_link_mesh,
            label="Duplicate As Linked Mesh",
            anchor_operator="object.join",
            before_anchor=True,
            is_enabled=_n2m_is_link_mesh_enabled,
            icon='MESH_DATA',
        )
    print("Registered NURBS2Mesh")

def unregister():
    global _OBJECT_MENU_ITEM
    if _OBJECT_MENU_ITEM is not None:
        unregister_menu_item(_OBJECT_MENU_ITEM)
        _OBJECT_MENU_ITEM = None
    if depsgraph_update_handler in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(depsgraph_update_handler)
    if load_post_handler in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(load_post_handler)
    clear_runtime_state()
    del bpy.types.Object.n2m
    for c in reversed(_CLASSES):
        bpy.utils.unregister_class(c)
