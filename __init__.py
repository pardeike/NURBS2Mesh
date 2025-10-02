# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025 Andreas

bl_info = {
    "name": "NURBS2Mesh",
    "author": "Andreas",
    "version": (1, 0, 0),
    "blender": (4, 0, 0),
    "location": "Object Properties > NURBS2Mesh",
    "description": "Auto-updating mesh copy from NURBS/Curve/Surface with debounce",
    "category": "Object",
}

import bpy
import functools
from bpy.app.handlers import persistent
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

# --------------------------
# Internal state
# --------------------------

_TIMERS = {}  # src_name -> timer function

def _targets_for_source(src):
    """Find mesh objects linked to a given source object."""
    res = []
    if src is None:
        return res
    for o in bpy.data.objects:
        if o.type == 'MESH' and hasattr(o, "n2m") and o.n2m.source == src:
            res.append(o)
    return res

def _first_users_collection(obj, context):
    u = getattr(obj, "users_collection", ())
    if u:
        return u[0]
    return context.scene.collection

def _safe_replace_mesh(obj_mesh, new_mesh):
    """Swap mesh datablock on an object and free previous if unused."""
    old = obj_mesh.data
    obj_mesh.data = new_mesh
    if old and old.users == 0:
        bpy.data.meshes.remove(old)

def _build_mesh_from_object(src_obj, *, apply_modifiers=True, preserve_all=True):
    """Create a new Mesh datablock from source object using Blender's conversion."""
    # Use evaluated object to match viewport conversion, including modifiers.
    # This follows Blender's documented behavior for new_from_object.
    depsgraph = bpy.context.evaluated_depsgraph_get()
    obj_eval = src_obj.evaluated_get(depsgraph) if apply_modifiers else src_obj
    mesh = bpy.data.meshes.new_from_object(
        obj_eval,
        preserve_all_data_layers=preserve_all,
        depsgraph=depsgraph if preserve_all else None,
    )
    return mesh

def _schedule_update(src_obj):
    """Debounce updates per source using bpy.app.timers."""
    if src_obj is None:
        return
    src_name = src_obj.name
    # Pick the smallest positive debounce among auto-updating targets.
    targets = [t for t in _targets_for_source(src_obj) if t.n2m.auto_update]
    if not targets:
        return
    delay = min(max(t.n2m.debounce, 0.0) for t in targets)

    if src_name in _TIMERS:
        # Timer already scheduled.
        return

    def _run():
        try:
            _update_now_by_source_name(src_name)
        finally:
            _TIMERS.pop(src_name, None)
        return None  # one-shot
    _TIMERS[src_name] = _run
    bpy.app.timers.register(_run, first_interval=delay)

def _update_now_by_source_name(src_name):
    src = bpy.data.objects.get(src_name)
    if src is None:
        return
    targets = [t for t in _targets_for_source(src) if t.n2m.auto_update]
    if not targets:
        return
    for t in targets:
        if not t.n2m.source:
            continue
        try:
            mesh = _build_mesh_from_object(
                t.n2m.source,
                apply_modifiers=t.n2m.apply_modifiers,
                preserve_all=t.n2m.preserve_all_data_layers,
            )
            _safe_replace_mesh(t, mesh)
        except Exception as ex:
            print(f"[NURBS2Mesh] Update failed for {t.name}: {ex}")

# --------------------------
# Properties
# --------------------------

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

# --------------------------
# Operators
# --------------------------

class N2M_OT_link_mesh(Operator):
    bl_idname = "n2m.link_mesh"
    bl_label = "Link Mesh Copy"
    bl_options = {'REGISTER', 'UNDO'}

    create_separate_object: BoolProperty(
        name="Create New Mesh Object",
        default=True
    )

    def execute(self, context):
        src = context.object
        if src is None or src.type not in {'CURVE', 'SURFACE'}:
            self.report({'ERROR'}, "Select a NURBS/Curve/Surface object")
            return {'CANCELLED'}

        prefs = context.preferences.addons[__name__].preferences

        mesh = _build_mesh_from_object(src)
        name_base = f"{src.name}_N2M"
        new_obj = bpy.data.objects.new(name_base, mesh)
        coll = _first_users_collection(src, context)
        coll.objects.link(new_obj)

        # Keep world transform in sync by parenting, so transform changes don't force remesh.
        if prefs.auto_parent:
            new_obj.parent = src
            new_obj.matrix_parent_inverse = src.matrix_world.inverted()

        # Initialize link properties on the target mesh object.
        new_obj.n2m.source = src
        new_obj.n2m.debounce = prefs.default_debounce
        new_obj.n2m.auto_update = True
        new_obj.n2m.apply_modifiers = True
        new_obj.n2m.preserve_all_data_layers = True

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
            _update_now_by_source_name(src.name)
            return {'FINISHED'}
        if obj and obj.type in {'CURVE', 'SURFACE'}:
            _update_now_by_source_name(obj.name)
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
        obj.n2m.source = None
        self.report({'INFO'}, "Unlinked mesh from source")
        return {'FINISHED'}

# --------------------------
# Panel
# --------------------------

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
            layout.operator(N2M_OT_link_mesh.bl_idname, icon='MESH_DATA')
            layout.separator()
            targets = _targets_for_source(o)
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

# --------------------------
# Handlers
# --------------------------

@persistent
def _n2m_on_depsgraph_update(scene, depsgraph):
    # Cheap early-out.
    if not (depsgraph.id_type_updated('OBJECT') or depsgraph.id_type_updated('CURVE')):
        return

    for upd in depsgraph.updates:
        id_ = upd.id

        # Object updates: only react to geometry changes for curve/surface objects.
        if isinstance(id_, bpy.types.Object):
            if id_.type in {'CURVE', 'SURFACE'} and upd.is_updated_geometry:
                _schedule_update(id_)

        # Curve datablock updates: *always* schedule; the flag is not reliable for Curves.
        elif isinstance(id_, bpy.types.Curve):
            for obj in (o for o in bpy.data.objects
                        if o.type in {'CURVE', 'SURFACE'} and o.data is id_):
                _schedule_update(obj)

@persistent
def _n2m_on_load_post(dummy):
    # Clear pending timers and rebuild nothing; links are discovered lazily.
    for fn in list(_TIMERS.values()):
        if bpy.app.timers.is_registered(fn):
            bpy.app.timers.unregister(fn)
    _TIMERS.clear()

# --------------------------
# Register
# --------------------------

_CLASSES = (
    N2M_Preferences,
    N2M_LinkProps,
    N2M_OT_link_mesh,
    N2M_OT_update_now,
    N2M_OT_unlink,
    N2M_PT_panel,
)

def register():
    for c in _CLASSES:
        bpy.utils.register_class(c)
    bpy.types.Object.n2m = PointerProperty(type=N2M_LinkProps)
    # Handlers
    if _n2m_on_depsgraph_update not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_n2m_on_depsgraph_update)
    if _n2m_on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_n2m_on_load_post)

def unregister():
    # Handlers
    if _n2m_on_depsgraph_update in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_n2m_on_depsgraph_update)
    if _n2m_on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_n2m_on_load_post)
    # Timers
    for fn in list(_TIMERS.values()):
        if bpy.app.timers.is_registered(fn):
            bpy.app.timers.unregister(fn)
    _TIMERS.clear()
    # Classes and props
    del bpy.types.Object.n2m
    for c in reversed(_CLASSES):
        bpy.utils.unregister_class(c)
