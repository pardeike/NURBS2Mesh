# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025 Andreas Pardeike

bl_info = {
    "name": "NURBS2Mesh",
    "author": "Andreas",
    "version": (1, 0, 0),
    "blender": (4, 0, 0),
    "location": "Object Properties > NURBS2Mesh",
    "description": "Auto-updating mesh copy from NURBS/Curve/Surface with debounce",
    "category": "Object",
}

import hashlib
import struct
import bpy
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

_FP = {}  # source_name -> last fingerprint


def _targets_for_source(src):
    """Find mesh objects linked to a given source object."""
    res = []
    if src is None:
        return res
    src_name = getattr(src, 'name', None)
    for obj in bpy.data.objects:
        if obj.type != 'MESH':
            continue
        link = getattr(obj, 'n2m', None)
        if not link or not hasattr(link, 'bl_rna'):
            continue
        if not getattr(link, 'auto_update', False):
            continue
        link_src = getattr(link, 'source', None)
        if link_src == src:
            res.append(obj)
            continue
        if src_name and getattr(link_src, 'name', None) == src_name:
            res.append(obj)
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
        return None
    src_name = src_obj.name
    targets = _targets_for_source(src_obj)
    if not targets:
        return None
    delay = min(max(t.n2m.debounce, 0.0) for t in targets)
    if src_name in _TIMERS:
        return None

    def _run():
        try:
            _update_now_by_source_name(src_name)
        finally:
            _TIMERS.pop(src_name, None)
        return None  # one-shot

    _TIMERS[src_name] = _run
    bpy.app.timers.register(_run, first_interval=delay)
    return delay

def _update_now_by_source_name(src_name):
    src = bpy.data.objects.get(src_name)
    if src is None:
        _FP.pop(src_name, None)
        return
    targets = _targets_for_source(src)
    if not targets:
        return
    for target in targets:
        link = getattr(target, 'n2m', None)
        if not link or not link.source:
            continue
        try:
            mesh = _build_mesh_from_object(
                link.source,
                apply_modifiers=link.apply_modifiers,
                preserve_all=link.preserve_all_data_layers,
            )
            _safe_replace_mesh(target, mesh)
        except Exception as ex:
            print(f"[NURBS2Mesh] Update failed for {target.name}: {ex}")


def _float_bytes(v: float) -> bytes:
    return struct.pack('<d', float(v))


def _curve_fingerprint(src_obj) -> str | None:
    data = getattr(src_obj, 'data', None)
    if not data or not isinstance(data, bpy.types.Curve):
        return None
    h = hashlib.blake2b(digest_size=16)

    for name in (
        'dimensions', 'resolution_u', 'resolution_v',
        'render_resolution_u', 'render_resolution_v',
        'bevel_depth', 'bevel_resolution', 'extrude', 'offset',
        'twist_smooth', 'use_fill_caps', 'use_fill_deform',
    ):
        if hasattr(data, name):
            h.update(str(getattr(data, name)).encode())

    for spl in data.splines:
        h.update(spl.type.encode())
        for name in ('use_cyclic_u', 'use_cyclic_v', 'order_u', 'order_v', 'resolution_u', 'resolution_v'):
            if hasattr(spl, name):
                h.update(str(getattr(spl, name)).encode())
        if spl.type == 'BEZIER' and hasattr(spl, 'bezier_points'):
            for bp in spl.bezier_points:
                for vec in (bp.handle_left, bp.co, bp.handle_right):
                    for f in vec:
                        h.update(_float_bytes(f))
                h.update(_float_bytes(bp.tilt))
                h.update(_float_bytes(bp.radius))
        elif spl.type in {'NURBS', 'POLY'} and hasattr(spl, 'points'):
            for p in spl.points:
                for f in p.co:
                    h.update(_float_bytes(f))
                h.update(_float_bytes(getattr(p, 'tilt', 0.0)))
                h.update(_float_bytes(getattr(p, 'radius', 1.0)))
        elif spl.type == 'SURFACE' and hasattr(spl, 'points'):
            for row in spl.points:
                rows = row if isinstance(row, (list, tuple)) else [row]
                for p in rows:
                    for f in getattr(p, 'co', (0.0, 0.0, 0.0, 0.0)):
                        h.update(_float_bytes(f))
                    h.update(_float_bytes(getattr(p, 'tilt', 0.0)))
                    h.update(_float_bytes(getattr(p, 'radius', 1.0)))
        elif hasattr(spl, 'points'):
            for p in spl.points:
                for f in getattr(p, 'co', (0.0, 0.0, 0.0, 0.0)):
                    h.update(_float_bytes(f))
                h.update(_float_bytes(getattr(p, 'tilt', 0.0)))
                h.update(_float_bytes(getattr(p, 'radius', 1.0)))
    return h.hexdigest()


def _geometry_changed(src_obj) -> bool:
    src_name = getattr(src_obj, 'name', None)
    if not src_name:
        return False
    fp = _curve_fingerprint(src_obj)
    if fp is None:
        return True
    prev = _FP.get(src_name)
    if prev == fp:
        return False
    _FP[src_name] = fp
    return True

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
    bl_label = "Duplicate As Linked Mesh"
    bl_options = {'REGISTER', 'UNDO'}

    create_separate_object = BoolProperty(
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

        if prefs.auto_parent:
            new_obj.parent = src
            new_obj.matrix_parent_inverse = src.matrix_world.inverted()

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
                _update_now_by_source_name(src.name)
            else:
                self.report({'ERROR'}, 'Linked source is missing')
                return {'CANCELLED'}
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
        src = obj.n2m.source
        obj.n2m.source = None
        if src and getattr(src, 'name', None):
            _FP.pop(src.name, None)
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
            layout.operator(N2M_OT_link_mesh.bl_idname, text="Duplicate As Linked Mesh", icon='MESH_DATA')
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
    if not (depsgraph.id_type_updated('OBJECT') or depsgraph.id_type_updated('CURVE')):
        return
    for upd in depsgraph.updates:
        id_ = upd.id
        if isinstance(id_, bpy.types.Object):
            if id_.type in {'CURVE', 'SURFACE'} and upd.is_updated_geometry:
                if _geometry_changed(id_):
                    _schedule_update(id_)
        elif isinstance(id_, bpy.types.Curve):
            for obj in (o for o in bpy.data.objects if o.type in {'CURVE', 'SURFACE'} and o.data is id_):
                if _geometry_changed(obj):
                    _schedule_update(obj)


@persistent
def _n2m_on_load_post(dummy):
    # Clear pending timers and rebuild nothing; links are discovered lazily.
    for fn in list(_TIMERS.values()):
        if bpy.app.timers.is_registered(fn):
            bpy.app.timers.unregister(fn)
    _TIMERS.clear()
    _FP.clear()

# --------------------------
# UI integration
# --------------------------

_ORIGINAL_OBJECT_MENU_DRAW = None

def _n2m_object_menu_draw(self, context):
    layout = self.layout

    # Recreate Blender's object menu so we can slip in our operator after Duplicate Linked.
    ob = context.object

    layout.menu("VIEW3D_MT_transform_object")
    layout.operator_menu_enum("object.origin_set", text="Set Origin", property="type")
    layout.menu("VIEW3D_MT_mirror")
    layout.menu("VIEW3D_MT_object_clear")
    layout.menu("VIEW3D_MT_object_apply")
    layout.menu("VIEW3D_MT_snap")

    layout.separator()

    layout.operator("object.duplicate_move")
    layout.operator("object.duplicate_move_linked")
    layout.operator(N2M_OT_link_mesh.bl_idname, text="Duplicate As Linked Mesh", icon='MESH_DATA')
    layout.operator("object.join")

    layout.separator()

    layout.operator("view3d.copybuffer", text="Copy Objects", icon='COPYDOWN')
    layout.operator("view3d.pastebuffer", text="Paste Objects", icon='PASTEDOWN')

    layout.separator()

    layout.menu("VIEW3D_MT_object_asset", icon='ASSET_MANAGER')
    layout.menu("VIEW3D_MT_object_collection")

    layout.separator()

    layout.menu("VIEW3D_MT_object_liboverride", icon='LIBRARY_DATA_OVERRIDE')
    layout.menu("VIEW3D_MT_object_relations")
    layout.menu("VIEW3D_MT_object_parent")
    layout.menu("VIEW3D_MT_object_modifiers", icon='MODIFIER')
    layout.menu("VIEW3D_MT_object_constraints", icon='CONSTRAINT')
    layout.menu("VIEW3D_MT_object_track")
    layout.menu("VIEW3D_MT_make_links")

    layout.separator()

    layout.operator("object.shade_smooth")
    if ob and ob.type == 'MESH':
        layout.operator("object.shade_auto_smooth")
    layout.operator("object.shade_flat")

    layout.separator()

    layout.menu("VIEW3D_MT_object_animation")
    layout.menu("VIEW3D_MT_object_rigid_body")

    layout.separator()

    layout.menu("VIEW3D_MT_object_quick_effects")

    layout.separator()

    layout.menu("VIEW3D_MT_object_convert")

    layout.separator()

    layout.menu("VIEW3D_MT_object_showhide")
    layout.menu("VIEW3D_MT_object_cleanup")

    layout.separator()

    layout.operator_context = 'EXEC_REGION_WIN'
    layout.operator("object.delete", text="Delete").use_global = False
    layout.operator("object.delete", text="Delete Global").use_global = True

    layout.template_node_operator_asset_menu_items(catalog_path="Object")

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
    global _ORIGINAL_OBJECT_MENU_DRAW
    print('[NURBS2Mesh] register from', __file__)
    if _ORIGINAL_OBJECT_MENU_DRAW is None:
        _ORIGINAL_OBJECT_MENU_DRAW = bpy.types.VIEW3D_MT_object.draw
    bpy.types.VIEW3D_MT_object.draw = _n2m_object_menu_draw
    for c in _CLASSES:
        bpy.utils.register_class(c)
    bpy.types.Object.n2m = PointerProperty(type=N2M_LinkProps)
    if _n2m_on_depsgraph_update not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_n2m_on_depsgraph_update)
    if _n2m_on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_n2m_on_load_post)

def unregister():
    global _ORIGINAL_OBJECT_MENU_DRAW
    print('[NURBS2Mesh] unregister from', __file__)
    if _ORIGINAL_OBJECT_MENU_DRAW is not None:
        bpy.types.VIEW3D_MT_object.draw = _ORIGINAL_OBJECT_MENU_DRAW
        _ORIGINAL_OBJECT_MENU_DRAW = None
    if _n2m_on_depsgraph_update in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_n2m_on_depsgraph_update)
    if _n2m_on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_n2m_on_load_post)
    for fn in list(_TIMERS.values()):
        if bpy.app.timers.is_registered(fn):
            bpy.app.timers.unregister(fn)
    _TIMERS.clear()
    _FP.clear()
    del bpy.types.Object.n2m
    for c in reversed(_CLASSES):
        bpy.utils.unregister_class(c)
