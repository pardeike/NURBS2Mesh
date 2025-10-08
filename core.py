"""
Core utilities for the NURBS2Mesh add-on.

This module keeps runtime state (timers, fingerprints), exposes helper
functions used by operators/UI, and defines the persistent handlers that
coordinate automatic updates.
"""

from __future__ import annotations

import hashlib
import struct
from typing import Iterable, List, Optional

import bpy
from bpy.app.handlers import persistent
from bpy.types import Object
from mathutils import Matrix, Vector

__all__ = [
    "linked_meshes_for_source",
    "first_user_collection",
    "build_mesh_from_source",
    "update_now_by_name",
    "schedule_update",
    "forget_fingerprint",
    "depsgraph_update_handler",
    "load_post_handler",
    "clear_runtime_state",
]


# Runtime state -------------------------------------------------------------

_timers: dict[str, callable] = {}
_fingerprints: dict[str, str] = {}


def clear_runtime_state() -> None:
    """Stop all scheduled timers and reset cached fingerprints."""
    for fn in list(_timers.values()):
        if bpy.app.timers.is_registered(fn):
            bpy.app.timers.unregister(fn)
    _timers.clear()
    _fingerprints.clear()


def forget_fingerprint(src_name: str) -> None:
    """Remove cached state for a source object by name."""
    _fingerprints.pop(src_name, None)


# Geometry helpers ----------------------------------------------------------

def linked_meshes_for_source(
    src: Optional[Object],
    *,
    include_disabled: bool = False,
) -> List[Object]:
    """Return all mesh objects linked to *src* via the n2m property."""
    if src is None:
        return []
    src_name = getattr(src, "name", None)
    result: List[Object] = []
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        link = getattr(obj, "n2m", None)
        if not link or not getattr(link, "bl_rna", None):
            continue
        if not include_disabled and not getattr(link, "auto_update", False):
            continue
        link_src = getattr(link, "source", None)
        if link_src == src:
            result.append(obj)
        elif src_name and getattr(link_src, "name", None) == src_name:
            result.append(obj)
    return result


def first_user_collection(obj: Object, context: bpy.types.Context):
    """Return the first collection using *obj* or the scene collection."""
    collections = getattr(obj, "users_collection", ())
    if collections:
        return collections[0]
    return context.scene.collection


def _first_open_spline_start_local(curve: bpy.types.Curve):
    opens = [s for s in curve.splines if not getattr(s, "use_cyclic_u", False)]
    if len(opens) != 1:
        return None
    spline = opens[0]
    if spline.type == "BEZIER" and spline.bezier_points:
        return spline.bezier_points[0].co.copy()
    if hasattr(spline, "points") and spline.points:
        v = spline.points[0].co  # x, y, z, w
        w = v[3] if v[3] != 0.0 else 1.0
        return Vector((v[0] / w, v[1] / w, v[2] / w))
    return None


def _apply_curve_origin_fix(mesh: bpy.types.Mesh, src_obj: Object):
    data = getattr(src_obj, "data", None)
    if not isinstance(data, bpy.types.Curve):
        return
    start = _first_open_spline_start_local(data)
    if start is None:
        return
    mesh.transform(Matrix.Translation(-start))


def build_mesh_from_source(
    src_obj: Object,
    *,
    apply_modifiers: bool = True,
    preserve_all: bool = True,
) -> bpy.types.Mesh:
    """Create a mesh datablock from ``src_obj`` respecting add-on settings."""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = src_obj.evaluated_get(depsgraph) if apply_modifiers else src_obj
    mesh = bpy.data.meshes.new_from_object(
        evaluated,
        preserve_all_data_layers=preserve_all,
        depsgraph=depsgraph if preserve_all else None,
    )
    _apply_curve_origin_fix(mesh, src_obj)
    return mesh


def _replace_object_mesh(obj_mesh: Object, new_mesh: bpy.types.Mesh) -> None:
    """Attach ``new_mesh`` to ``obj_mesh`` and release the previous datablock."""
    previous = obj_mesh.data
    obj_mesh.data = new_mesh
    if previous and previous.users == 0:
        old_name = getattr(previous, "name", None)
        bpy.data.meshes.remove(previous)
        if old_name:
            new_mesh.name = old_name


# Update orchestration ------------------------------------------------------

def _float_bytes(value: float) -> bytes:
    return struct.pack("<d", float(value))


def _modifier_fingerprint(obj: Object) -> bytes:
    modifiers = getattr(obj, "modifiers", None)
    if not modifiers:
        return b""

    parts: List[str] = []
    for mod in modifiers:
        entries: List[str] = [
            mod.type,
            "1" if getattr(mod, "show_viewport", True) else "0",
        ]
        if hasattr(mod, "show_render"):
            entries.append("1" if mod.show_render else "0")

        properties = []
        for prop in mod.bl_rna.properties:
            if prop.is_readonly or prop.identifier in {
                "rna_type",
                "name",
                "type",
                "show_viewport",
                "show_render",
            }:
                continue
            try:
                value = getattr(mod, prop.identifier)
            except AttributeError:
                continue
            if prop.type == "POINTER":
                value = getattr(value, "name", None)
            elif prop.type == "COLLECTION":
                value = tuple(getattr(item, "name", None) for item in value)
            properties.append((prop.identifier, value))
        if properties:
            entries.append(repr(sorted(properties)))

        parts.append("|".join(entries))

    return "\u0001".join(parts).encode()


def _curve_fingerprint(src_obj: Object) -> Optional[str]:
    data = getattr(src_obj, "data", None)
    if not isinstance(data, bpy.types.Curve):
        return None

    hasher = hashlib.blake2b(digest_size=16)

    for name in (
        "dimensions",
        "resolution_u",
        "resolution_v",
        "render_resolution_u",
        "render_resolution_v",
        "bevel_depth",
        "bevel_resolution",
        "extrude",
        "offset",
        "twist_smooth",
        "use_fill_caps",
        "use_fill_deform",
    ):
        if hasattr(data, name):
            hasher.update(str(getattr(data, name)).encode())

    for spline in data.splines:
        hasher.update(spline.type.encode())
        for name in (
            "use_cyclic_u",
            "use_cyclic_v",
            "order_u",
            "order_v",
            "resolution_u",
            "resolution_v",
        ):
            if hasattr(spline, name):
                hasher.update(str(getattr(spline, name)).encode())

        if spline.type == "BEZIER" and hasattr(spline, "bezier_points"):
            points: Iterable = spline.bezier_points
            for point in points:
                for vec in (point.handle_left, point.co, point.handle_right):
                    for component in vec:
                        hasher.update(_float_bytes(component))
                hasher.update(_float_bytes(point.tilt))
                hasher.update(_float_bytes(point.radius))
        elif spline.type in {"NURBS", "POLY"} and hasattr(spline, "points"):
            for point in spline.points:
                for component in point.co:
                    hasher.update(_float_bytes(component))
                hasher.update(_float_bytes(getattr(point, "tilt", 0.0)))
                hasher.update(_float_bytes(getattr(point, "radius", 1.0)))
        elif spline.type == "SURFACE" and hasattr(spline, "points"):
            for column in spline.points:
                points = column if isinstance(column, (list, tuple)) else [column]
                for point in points:
                    for component in getattr(point, "co", (0.0, 0.0, 0.0, 0.0)):
                        hasher.update(_float_bytes(component))
                    hasher.update(_float_bytes(getattr(point, "tilt", 0.0)))
                    hasher.update(_float_bytes(getattr(point, "radius", 1.0)))
        elif hasattr(spline, "points"):
            for point in spline.points:
                for component in getattr(point, "co", (0.0, 0.0, 0.0, 0.0)):
                    hasher.update(_float_bytes(component))
                hasher.update(_float_bytes(getattr(point, "tilt", 0.0)))
                hasher.update(_float_bytes(getattr(point, "radius", 1.0)))

    hasher.update(_modifier_fingerprint(src_obj))
    return hasher.hexdigest()


def _geometry_changed(src_obj: Object) -> bool:
    src_name = getattr(src_obj, "name", None)
    if not src_name:
        return False
    fingerprint = _curve_fingerprint(src_obj)
    if fingerprint is None:
        return True
    previous = _fingerprints.get(src_name)
    if previous == fingerprint:
        return False
    _fingerprints[src_name] = fingerprint
    return True


def schedule_update(src_obj: Optional[Object]) -> Optional[float]:
    """Debounce updates for ``src_obj`` using ``bpy.app.timers``."""
    if src_obj is None:
        return None

    src_name = src_obj.name
    targets = linked_meshes_for_source(src_obj)
    if not targets:
        return None

    delay = min(max(t.n2m.debounce, 0.0) for t in targets)
    if src_name in _timers:
        existing = _timers.pop(src_name)
        if bpy.app.timers.is_registered(existing):
            bpy.app.timers.unregister(existing)

    def _run():
        try:
            update_now_by_name(src_name)
        finally:
            _timers.pop(src_name, None)
        return None

    _timers[src_name] = _run
    bpy.app.timers.register(_run, first_interval=delay)
    return delay


def update_now_by_name(src_name: str, *, include_disabled: bool = False) -> None:
    """Synchronise all linked meshes whose source matches ``src_name``."""
    src = bpy.data.objects.get(src_name)
    if src is None:
        forget_fingerprint(src_name)
        return

    targets = linked_meshes_for_source(src, include_disabled=include_disabled)
    if not targets:
        return

    for mesh_obj in targets:
        link = getattr(mesh_obj, "n2m", None)
        if not link or not link.source:
            continue
        try:
            mesh = build_mesh_from_source(
                link.source,
                apply_modifiers=link.apply_modifiers,
                preserve_all=link.preserve_all_data_layers,
            )
            _replace_object_mesh(mesh_obj, mesh)
        except Exception as ex:  # pragma: no cover - Blender context dependent
            print(f"[NURBS2Mesh] Update failed for {mesh_obj.name}: {ex}")


# Handlers ------------------------------------------------------------------

@persistent
def depsgraph_update_handler(scene, depsgraph):
    if not (depsgraph.id_type_updated("OBJECT") or depsgraph.id_type_updated("CURVE")):
        return
    for update in depsgraph.updates:
        data_id = update.id
        if isinstance(data_id, bpy.types.Object):
            if data_id.type in {"CURVE", "SURFACE"} and update.is_updated_geometry:
                if _geometry_changed(data_id):
                    schedule_update(data_id)
        elif isinstance(data_id, bpy.types.Curve):
            for obj in (
                candidate
                for candidate in bpy.data.objects
                if candidate.type in {"CURVE", "SURFACE"} and candidate.data is data_id
            ):
                if _geometry_changed(obj):
                    schedule_update(obj)


@persistent
def load_post_handler(_dummy):
    clear_runtime_state()
