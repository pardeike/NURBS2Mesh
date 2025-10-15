# NURBS2Mesh

<img alt="Nurbs2MeshScreenshot" src="https://github.com/user-attachments/assets/62fb45ae-e11d-4b27-a256-1e4a4d998539" />

NURBS2Mesh keeps a mesh copy in sync with any NURBS, Curve, or Surface object so you can keep a non-destructive workflow and still use mesh-only tools such as Boolean modifiers, physics, and export formats that require polygon data.

## Key Features

- Automatic mesh mirrors of your curve and surface objects
- Debounced updates to avoid costly recomputation while editing
- Optional inclusion of evaluated modifiers from the source object
- Preservation of UV maps, vertex groups, and other data layers when possible
- Per-mesh controls for auto-update, debounce timing, and manual refresh
- Support for multiple linked meshes from a single source
- Convenient entry in the Object menu (`Duplicate As Linked Mesh`)

## Supported Blender Versions

- Blender 4.2 and newer via the Extensions manager
- Blender 4.0–4.1 via manual add-on installation

## Installation

### Blender 4.2+

1. Download the latest release ZIP or clone this repository.
2. Open Blender and go to `Edit > Preferences > Get Extensions`.
3. Use the menu (three dots) in the upper-right corner and choose `Install from Disk...`.
4. Select the downloaded ZIP or project folder.
5. Enable **NURBS2Mesh** in the Extensions list.

### Blender 4.0–4.1 (manual add-on install)

1. Download or clone this repository.
2. Copy the folder to your add-ons directory:
   - Windows: `%APPDATA%\Blender Foundation\Blender\<version>\scripts\addons\nurbs2mesh\`
   - macOS: `~/Library/Application Support/Blender/<version>/scripts/addons/nurbs2mesh/`
   - Linux: `~/.config/blender/<version>/scripts/addons/nurbs2mesh/`
3. Open `Edit > Preferences > Add-ons`, search for **NURBS2Mesh**, and enable it.

## Getting Started

1. Select a NURBS, Curve, or Surface object in your scene.
2. In the **Object Properties** sidebar, locate the **NURBS2Mesh** panel.
3. Click **Duplicate As Linked Mesh**.

A mesh with the suffix ` Mesh` appears and is linked to the source object. By default the mesh is parented to keep transforms aligned. Edits to the source object propagate to the mesh automatically.

### Managing Linked Meshes

With a curve or surface selected:
- **Duplicate As Linked Mesh** creates additional mesh copies.
- **Linked Meshes** lists every mesh linked to the source. Each entry offers an auto-update toggle and a manual refresh button.

With a linked mesh selected:
- **Source** points to the driving curve or surface.
- **Auto Update** toggles whether edits to the source cause updates.
- **Debounce (s)** sets the minimum time between updates (default 0.25 s).
- **Apply Modifiers from Source** includes the evaluated modifier stack when building the mesh.
- **Preserve All Data Layers** attempts to keep UVs, vertex groups, and similar data.
- **Update Now** forces an immediate sync.
- **Unlink** breaks the connection so the mesh can be edited independently.

You can also access **Duplicate As Linked Mesh** from the Object menu in the 3D Viewport; the command is inserted just before Blender’s built-in **Join** entry.

## Tips & Best Practices

- Increase the debounce value if you work with heavy geometry or large scenes.
- Disable **Apply Modifiers from Source** when you only need raw curve geometry.
- Create multiple linked meshes if you want different modifier stacks or export settings per copy.
- Temporarily turn off auto updates while making sweeping changes to the source curve, then trigger **Update Now**.

## Troubleshooting

- **Mesh is not updating**  
  Confirm auto update is enabled, ensure the source object still exists, and try **Update Now**. Check Blender’s console for error messages if the update fails.

- **Viewport feels slow**  
  Raise the debounce interval, disable modifier inclusion, or turn off auto updates temporarily.

- **Source was deleted or renamed**  
  Use the **Source** property on the linked mesh to pick a new curve, or unlink and create a fresh copy.

## License & Credits

NURBS2Mesh is licensed under the GNU General Public License v3.0 or later.

Copyright © 2025 Andreas Pardeike

Author: Andreas Pardeike (Brrainz)  
GitHub: <https://github.com/pardeike/NURBS2Mesh>
