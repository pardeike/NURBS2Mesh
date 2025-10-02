# Quick Reference: Issues by Priority

## 🔴 CRITICAL - Fix Immediately

### Issue #1: Dead Code (Line 166)
```diff
def _modifier_fingerprint(obj) -> bytes:
    # ... code ...
    return '\u0001'.join(parts).encode()
-   return struct.pack('<d', float(v))  # ← DELETE THIS LINE
```
**Fix**: Delete line 166  
**Time**: 1 minute  
**Risk**: None

---

### Issue #2: Mesh Name Not Preserved
```diff
def _safe_replace_mesh(obj_mesh, new_mesh):
    """Swap mesh datablock on an object and free previous if unused."""
    old = obj_mesh.data
+   old_name = old.name if old else None
    obj_mesh.data = new_mesh
+   if old_name and new_mesh:
+       new_mesh.name = old_name
    if old and old.users == 0:
        bpy.data.meshes.remove(old)
```
**Fix**: 3 lines added  
**Time**: 5 minutes  
**Risk**: Low - improves UX significantly

---

### Issue #3: Timer Race Condition
```diff
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
-       return None
+       # Cancel existing timer and reschedule
+       old_timer = _TIMERS[src_name]
+       if bpy.app.timers.is_registered(old_timer):
+           bpy.app.timers.unregister(old_timer)
```
**Fix**: Replace 1 line with 4 lines  
**Time**: 10 minutes  
**Risk**: Medium - test thoroughly

---

### Issue #4: Performance - O(n) Iteration
```diff
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
-           continue
-       if src_name and getattr(link_src, 'name', None) == src_name:
+       elif src_name and getattr(link_src, 'name', None) == src_name:
            res.append(obj)
    return res
```
**Fix**: Change `continue` to `elif`  
**Time**: 2 minutes  
**Risk**: Low - simple logic improvement

**Alternative**: Implement caching (30+ minutes, higher risk)

---

## 🟡 HIGH PRIORITY - Fix Soon

### Issue #5: Error Handling
Add try-catch and validation to `_build_mesh_from_object`:
```python
def _build_mesh_from_object(src_obj, *, apply_modifiers=True, preserve_all=True):
    """Create a new Mesh datablock from source object using Blender's conversion."""
    if src_obj is None:
        raise ValueError("Source object cannot be None")
    
    if not hasattr(src_obj, 'data'):
        raise ValueError(f"Source object {src_obj.name} has no geometry data")
    
    try:
        depsgraph = bpy.context.evaluated_depsgraph_get()
    except AttributeError:
        raise RuntimeError("Cannot build mesh: Blender context not available")
    
    # ... rest of function
```
**Time**: 15 minutes

---

### Issue #6: Remove Redundant Fingerprint Code
Delete lines 210-215 (redundant fallback):
```diff
-       elif hasattr(spl, 'points'):
-           for p in spl.points:
-               for f in getattr(p, 'co', (0.0, 0.0, 0.0, 0.0)):
-                   h.update(_float_bytes(f))
-               h.update(_float_bytes(getattr(p, 'tilt', 0.0)))
-               h.update(_float_bytes(getattr(p, 'radius', 1.0)))
```
**Time**: 2 minutes

---

### Issue #7: Cleanup Global State
Add cleanup in depsgraph handler:
```python
@persistent
def _n2m_on_depsgraph_update(scene, depsgraph):
    if not (depsgraph.id_type_updated('OBJECT') or depsgraph.id_type_updated('CURVE')):
        return
    
    # Cleanup deleted objects
    existing_names = {obj.name for obj in bpy.data.objects}
    for name in list(_FP.keys()):
        if name not in existing_names:
            _FP.pop(name, None)
            _TIMERS.pop(name, None)
    
    # ... rest of function
```
**Time**: 10 minutes

---

### Issue #8: Menu Integration
Replace entire menu draw with append:
```python
def _menu_func_n2m(self, context):
    if context.object and context.object.type in {'CURVE', 'SURFACE'}:
        self.layout.operator(N2M_OT_link_mesh.bl_idname, 
                           text="Duplicate As Linked Mesh", 
                           icon='MESH_DATA')

def register():
    # ... existing code ...
    bpy.types.VIEW3D_MT_object.append(_menu_func_n2m)

def unregister():
    # ... existing code ...
    bpy.types.VIEW3D_MT_object.remove(_menu_func_n2m)
```
**Time**: 15 minutes  
**Risk**: Medium - changes user experience

---

## Quick Fix Priority Order

1. **Issue #1** - Dead code (1 min) ✅ Zero risk
2. **Issue #4** - Continue→elif (2 min) ✅ Low risk  
3. **Issue #6** - Remove redundant code (2 min) ✅ Low risk
4. **Issue #2** - Preserve mesh name (5 min) ✅ Low risk
5. **Issue #3** - Timer reschedule (10 min) ⚠️ Test well
6. **Issue #7** - Global cleanup (10 min) ⚠️ Test well
7. **Issue #5** - Error handling (15 min) ✅ Low risk
8. **Issue #8** - Menu API (15 min) ⚠️ Changes UX

**Total Time for All Critical + High**: ~60 minutes

---

## Testing After Fixes

After implementing fixes, test:

1. ✓ Create curve, link mesh, verify name preserved
2. ✓ Rapid edits (10+ in 1 second) - check debouncing
3. ✓ Create/delete 100 objects - check memory
4. ✓ Test with 1000+ objects in scene - check performance
5. ✓ Test menu integration still works
6. ✓ Test error cases (delete source, invalid object, etc.)

---

## Files to Modify

All changes in: `__init__.py`

- Lines to delete: 2 (166, 210-215)
- Lines to add: ~25
- Functions to modify: 6
- Risk level: Low to Medium

---

*See CODE_REVIEW.md for complete analysis*
*See REVIEW_SUMMARY.md for executive overview*
