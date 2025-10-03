# NURBS2Mesh

**Auto-updating mesh copies from NURBS, Curves, and Surfaces in Blender**

NURBS2Mesh is a Blender extension that enables non-destructive parametric modeling by creating and maintaining automatic mesh proxies of your NURBS/Curve/Surface objects. This allows you to use boolean operations, modifiers, and other mesh-only features while still enjoying the benefits of parametric curve-based modeling.

## Why NURBS2Mesh?

When working with NURBS, Curves, and Surfaces in Blender, you often run into limitations:

- **Boolean operations** don't work directly on curves
- Many **modifiers** require mesh geometry
- **Physics simulations** need mesh objects
- **Export formats** often require polygon meshes

Traditional workflow solutions require manual conversion, which breaks the parametric nature of curves. Every time you adjust your curve, you have to manually reconvert it to mesh, losing your non-destructive workflow.

**NURBS2Mesh solves this** by automatically creating and maintaining a mesh copy that updates whenever you edit the source curve. This gives you the best of both worlds:

✅ Keep modeling with parametric NURBS and curves  
✅ Get a real-time updating mesh proxy for boolean operations  
✅ Apply modifiers that only work on meshes  
✅ Maintain a fully non-destructive workflow  
✅ Automatic debounced updates (no performance hit from constant recalculation)

## Features

- **Auto-updating mesh copies** - Changes to source NURBS/Curve/Surface objects automatically update linked mesh objects
- **Debounced updates** - Configurable delay prevents excessive recalculation during editing
- **Modifier support** - Optionally include evaluated modifiers from the source object
- **Data layer preservation** - Maintains UVs, vertex groups, and other data layers when possible
- **Multiple linked meshes** - Create multiple mesh copies from the same source
- **Manual control** - Update on-demand or disable auto-updates
- **Parent option** - Automatically parent mesh copies to source objects for synchronized transforms

## Installation

### Blender 4.2+

1. Download the latest release or clone this repository
2. In Blender, go to `Edit > Preferences > Get Extensions`
3. Click the dropdown menu (≡) in the top right and select `Install from Disk...`
4. Navigate to the downloaded folder or ZIP file and select it
5. Enable the "NURBS2Mesh" extension

### Blender 4.0-4.1

1. Download or clone this repository
2. Copy the files to your Blender add-ons directory:
   - **Windows**: `%APPDATA%\Blender Foundation\Blender\<version>\scripts\addons\nurbs2mesh\`
   - **macOS**: `~/Library/Application Support/Blender/<version>/scripts/addons/nurbs2mesh/`
   - **Linux**: `~/.config/blender/<version>/scripts/addons/nurbs2mesh/`
3. Open Blender Preferences (`Edit > Preferences`)
4. Go to `Add-ons` section
5. Search for "NURBS2Mesh" and enable the checkbox

## Usage

### Creating a Linked Mesh

1. **Select** a NURBS, Curve, or Surface object in your scene
2. Open the **Object Properties** panel (the orange square icon)
3. Find the **NURBS2Mesh** panel
4. Click **"Duplicate As Linked Mesh"**

A new mesh object will be created with the suffix " Mesh" and automatically linked to your source object. By default, it will be parented to the source object so transforms stay synchronized.

### Understanding the Interface

When you select a **NURBS/Curve/Surface object**, the NURBS2Mesh panel shows:
- **Duplicate As Linked Mesh** button - Creates a new linked mesh copy
- **Linked Meshes** list - Shows all mesh objects linked to this source
  - 🔴 Toggle icon - Enable/disable auto-update for each linked mesh
  - 🔄 Refresh icon - Manually update that specific mesh

When you select a **linked mesh object**, the NURBS2Mesh panel shows:
- **Source** - The NURBS/Curve/Surface object this mesh is linked to
- **Auto Update** - Enable/disable automatic updates when source changes
- **Debounce (s)** - Wait time after last edit before updating (default: 0.25 seconds)
- **Apply Modifiers from Source** - Include the source object's modifiers in the mesh
- **Preserve All Data Layers** - Maintain UVs, vertex groups, etc. during updates
- **Update Now** - Manually trigger an immediate update
- **Unlink** - Break the connection between mesh and source

### Basic Workflow Example

Here's a typical non-destructive modeling workflow:

1. **Create a curve** (e.g., a Bezier curve for a pipe or railing)
2. **Model parametrically** - Adjust curve points, use the Bevel modifier, Array modifier, etc.
3. **Create linked mesh** - Use NURBS2Mesh to create a mesh proxy
4. **Apply mesh operations** - Use Boolean modifier on the mesh to cut holes, combine with other objects, etc.
5. **Continue editing** - Any changes to the original curve automatically update the mesh!

### Working with Modifiers

The real power comes from combining parametric curves with mesh modifiers:

```
[NURBS Curve] ──→ [Linked Mesh] ──→ [Boolean Modifier] ──→ [Final Result]
      ↑                                                            ↓
      └────────── Edit anytime, mesh updates automatically ────────┘
```

**Example: Creating a window frame**
1. Model the frame profile with a curve
2. Use Array and Curve modifiers to create the frame shape
3. Create a linked mesh with NURBS2Mesh
4. Apply Boolean modifier to the linked mesh to cut window panes
5. Edit the original curve profile - the entire frame updates automatically!

### Performance Tips

- **Adjust debounce time** - For complex geometry, increase debounce to 0.5-1.0 seconds to reduce update frequency during heavy editing
- **Disable auto-update temporarily** - When doing major restructuring, turn off auto-update and manually update when ready
- **Use apply_modifiers wisely** - Disable this option if source modifiers don't affect the mesh result you need

## Configuration

### Add-on Preferences

Access via `Edit > Preferences > Add-ons > NURBS2Mesh`:

- **Default Debounce (s)** - Sets the default debounce time for newly created linked meshes (default: 0.25 seconds)
- **Parent new mesh to source** - When enabled, new mesh objects are automatically parented to their source (default: enabled)

### Per-Object Settings

Each linked mesh can be configured independently in the Object Properties panel:

- **Auto Update** - Toggle automatic updates
- **Debounce** - Adjust the delay before updates trigger
- **Apply Modifiers from Source** - Include source object's modifiers
- **Preserve All Data Layers** - Keep UV maps, vertex groups, etc.

## Technical Details

### How It Works

NURBS2Mesh uses Blender's depsgraph system to detect changes to source objects and triggers mesh regeneration after a configurable debounce period. The extension:

1. **Monitors** NURBS/Curve/Surface objects that have linked meshes
2. **Detects changes** by computing a fingerprint of geometry and modifiers
3. **Debounces updates** to prevent excessive recalculation during editing
4. **Regenerates mesh** using Blender's native conversion (`new_from_object`)
5. **Preserves data** by optionally maintaining data layers across updates

### Geometry Fingerprinting

The extension creates a unique fingerprint for each source object by hashing:
- Control point positions and properties
- Curve/surface resolution settings
- Modifier stack (when apply_modifiers is enabled)
- Object-level settings affecting geometry

This allows efficient change detection without storing full geometry copies.

### Update Mechanism

Updates use Blender's timer system to debounce rapid changes:
- Multiple edits within the debounce period only trigger one update
- Each source object has independent update timing
- Updates run in the background without blocking the UI
- Failed updates are logged but don't crash the extension

## Use Cases

### Architectural Modeling
- Create window and door frames with curves
- Apply booleans to cut openings in walls
- Edit frame profiles non-destructively

### Product Design
- Model with precise NURBS surfaces
- Apply mechanical details with mesh modifiers
- Maintain parametric control throughout

### Organic Modeling
- Use curves for guide rails
- Generate mesh with Skin modifier
- Apply Subdivision Surface on mesh proxy
- Edit curve shape and see results update

### Piping and Cables
- Draw path with curve
- Add Bevel for thickness
- Use linked mesh for collision detection
- Apply Array/Curve modifiers on mesh

## Limitations

- **Blender 4.0+** required - Uses features from modern Blender versions
- **Real-time updates** - Very complex geometry may cause brief UI pauses during updates
- **Modifier dependencies** - Some modifiers may not evaluate correctly in all contexts
- **Undo system** - Undoing source edits triggers updates; mesh changes can't be undone independently

## Troubleshooting

### Mesh doesn't update
- Check that **Auto Update** is enabled
- Verify the **Source** reference is still valid
- Try clicking **Update Now** manually
- Check the Blender console for error messages

### Performance issues
- Increase the **Debounce** time to reduce update frequency
- Disable **Apply Modifiers from Source** if not needed
- Temporarily disable **Auto Update** during heavy editing

### Lost connection to source
- Use the **Source** dropdown to relink to the correct object
- If source was deleted, you'll need to recreate the link or use **Unlink**

## Contributing

Contributions are welcome! Please feel free to submit issues or pull requests.

## License

This extension is licensed under the GNU General Public License v3.0 or later.

Copyright (C) 2025 Andreas Pardeike

## Credits

**Author**: Andreas Pardeike (Brrainz)  
**GitHub**: https://github.com/pardeike/NURBS2Mesh

---

**Made with ❤️ for the Blender community**

If you find this extension useful, consider supporting its development!
