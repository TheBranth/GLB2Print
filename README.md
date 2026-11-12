# GLB2Print — Universal 3D-Printing Preparation Tool

A fast, cross-platform standalone tool and GUI that converts textured `.glb` / `.gltf` 3D models (such as AI-generated models from Tripo, Meshy, Rodin, or game assets) directly into **3D-printing ready** `.3mf` and `.obj` files with baked vertex colors and **smart planar splitting**.

**Compatible with any slicer**: OrcaSlicer, Bambu Studio, PrusaSlicer, Creality Print, Cura, Snapmaker Orca, etc.

---

## Prerequisites & Requirements

Before using GLB2Print, ensure you have the following installed:

1. **Python 3.9+**:
   * Windows & macOS: Python comes with `tkinter` included by default.
   * Linux (Debian/Ubuntu): Ensure Tkinter is installed via `sudo apt install python3-tk`.
2. **Blender (3.6 LTS, 4.x, or 5.x)**:
   * Blender runs purely **headlessly in the background** — you never need to interact with it directly.
   * **Auto-Discovery**: GLB2Print automatically scans standard installation directories on launch:
     * **Windows**: `C:\Program Files\Blender Foundation\Blender*\`, `D:\Blender\`, `C:\Blender\`, and `PATH`.
     * **macOS**: `/Applications/Blender.app`, `~/Applications/Blender.app`, and Homebrew.
     * **Linux**: `/usr/bin/blender`, `/usr/local/bin/blender`, `/snap/bin/blender`, and `PATH`.
   * **Manual Config**: If Blender is installed in a non-standard directory, you can set it in the GUI under `⚙ Settings` or pass `--blender-path <path>` in the CLI.

---

## Key Features

* **Unified Single-Window Experience**: Controls (texture, decimation, staging, export) and the real-time Three.js 3D viewport live together in a single application window (powered by `pywebview` with automatic Chrome/Edge `--app` fallback). No split windows or tab clutter.
* **Direct Viewport Drag & Drop**: Drag any `.glb` or `.gltf` model straight from your desktop into the 3D viewport to inspect and prep it instantly.
* **Smooth 60 FPS Viewport Raycasting**: High-performance AABB screen pre-filtering ensures instant freehand lasso selection even on massive 2-million polygon models.
* **Clean Lifecycle Termination**: Automatically terminates background Python server processes as soon as the window is closed.
* **Interactive Lasso & Region Split ('Split to Parts')**: Draw freehand polygon lassos directly across the 3D model in the viewport. Choose between **Surface/Front-Facing Only** or **Through-Mesh** projection, with optional **Color-Boundary Snapping** to snap selection edges to high-contrast texture borders.
* **Click-Enabled 2-Point Knife Bias Cut & Detach**: Click 2 points anywhere on the model (e.g. across cheekbones, ear bases, or joints) to instantly place a laser-flat cut plane angled directly along your view. Includes a **Flip Side** toggle, a precision nudge slider, and a **✂ Detach to Part** action to slice off and stage modular pieces sequentially.
* **Snap Pegs & Sockets (Snap-fit)**: Check `[x] Add Snap Pegs & Sockets` on planar cuts to automatically integrate a male alignment pin on one side and a matching 0.2mm tolerance female socket hole on the other for seamless glue-up and assembly.
* **Unified Multi-Part Staging Deck**: Both the 2-Click Knife Plane and the Freehand Lasso share the same interactive staging deck! Group pieces into custom named parts (`Part_1_Cheek`, `Part_2_Cheek`, `Part_3_Center`) with live color-coded tints in the 3D viewport, and export all watertight, capped parts in a single pass.
* **Planar Cut Tool**: Flat plane cutting along arbitrary angles (2-Click Knife) or World X, Y, Z axes with interactive position sliders and live preview.
* **No More Manual Blender Baking**: Slicers cannot use UV-mapped 2D texture images for multi-color toolpaths. **GLB2Print automates this entire process headlessly in seconds.**
* **Texture Resizing Before Baking**: Downscale massive 4K textures (e.g. to 1024×1024 or 512×512) prior to sampling to dramatically speed up conversion and reduce memory overhead without any loss in FDM print quality.
* **Smart Polygon Decimation**: AI models typically come with 1–3 million micro-polygons. GLB2Print includes a quadric decimation engine that preserves silhouette edges and vertex colors while shrinking files from ~200MB down to ~3MB–25MB for lightning-fast slicing.
* **Auto-Ground to Print Bed**: Automatically computes the model's bounding box and shifts the lowest vertex to $Z = 0.0$ so the model sits flat on your build plate.
* **Cross-Platform**: Runs natively on **Windows**, **macOS**, and **Linux**.

---

## Quickstart (Unified Desktop App)

### 1. Launch the App
* **Windows**: Double-click `run_gui.bat` (or drag any `.glb` file directly onto `run_gui.bat`!).
* **macOS / Linux**: Double-click `run_gui.sh` (or run `python3 app_gui.py [model.glb]`).

GLB2Print will open as a native single desktop window (using `pywebview` or Chrome/Edge `--app` mode).

### 2. Using the Unified App
1. **Load Model**: Drag and drop any `.glb` directly into the 3D viewport, or click **📁 Open Model**.
2. **Inspect & Segment**:
   * **Full Model Mode**: Convert and export the entire solid model.
   * **Planar Cut Mode**: Cut along X, Y, or Z with live plane slider.
   * **Lasso Split Mode**: Hold `Shift` and drag a loop across the mesh to stage multiple custom parts with live color tints.
3. **Texture & Decimation**: Adjust pre-bake texture resolution (e.g. `1024px`) and target triangle count (e.g. `250k`).
4. Click **⚡ CONVERT FOR 3D PRINTING** (or **🚀 EXPORT STAGED PARTS**). Output files are saved in the same directory as the input model.

---

## Command Line Interface (CLI)

GLB2Print includes a full-featured CLI (`cli.py`) for automated terminal workflows, scripts, and batch processing.

### Usage Examples

```bash
# Open interactive 3D visual preview and cut tool
python cli.py badger.glb --preview

# Split model across the X axis at coordinate 0.0 with capped cut faces
python cli.py badger.glb --split-axis x --split-coord 0.0 -t 200000 -f both

# Convert a single GLB to both OBJ and 3MF with 250k faces and 1024px texture
python cli.py badger.glb -t 250000 -r 1024 -f both

# Convert all models in a folder and output to a dedicated directory
python cli.py models/*.glb -o output_prints/ -t 200000

# Keep 100% original mesh without decimation or texture downscaling
python cli.py model.glb -t 0 -r 0

# Scale model to 120 mm tall and ground to Z=0
python cli.py model.glb --height-mm 120

# Specify a custom Blender binary and save it as default
python cli.py model.glb --blender-path "D:/Blender/blender.exe" --set-blender-default
```

### CLI Flags & Options Reference

| Flag | Long Flag | Value / Type | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `inputs` | *(positional)* | `path/glob` | *(required)* | One or more `.glb` / `.gltf` files, or a wildcard pattern (e.g. `*.glb`). |
| | `--preview` | `flag` | `False` | Opens the **interactive 3D visual preview** and planar cut viewport. |
| | `--split-axis` | `none`, `x`, `y`, `z` | `none` | **Cut plane normal axis** for splitting model into 2 parts. |
| | `--split-coord` | `float` | `0.0` | Coordinate position along the split axis. |
| | `--no-split-cap` | `flag` | `False` | Disables hole capping (leaves cut surfaces open). By default, cuts are sealed watertight. |
| | `--parts-json` | `path` | `""` | Path to a JSON file defining multi-part face index mappings (generated by Lasso Split tool). |
| `-t` | `--triangles` | `integer` | `250000` | **Target polygon/triangle count**. Decimates mesh while preserving vertex colors. Set to `0` to keep the original mesh. |
| `-r` | `--texture-res` | `integer` | `1024` | **Max texture dimension (px)** before baking (e.g. `512`, `1024`, `2048`). Set to `0` to use full original texture. |
| `-f` | `--format` | `obj`, `3mf`, `both` | `both` | **Export format**: `obj` (vertex-colored OBJ), `3mf` (color-group 3MF), or `both`. |
| `-o` | `--output-dir` | `path` | Input folder | Destination directory for exported files. |
| | `--height-mm` | `float` | `0.0` | Target height in millimeters. Scales model uniformly. `0.0` preserves original model dimensions. |
| | `--no-ground` | `flag` | `False` | Disables auto-grounding. By default, the bottom vertex is shifted to $Z = 0.0$. |
| | `--blender-path` | `path` | Auto-detected | Custom path to the Blender executable. |
| | `--set-blender-default` | `flag` | `False` | Saves the custom `--blender-path` permanently to `glb2print_config.json`. |

### CLI Shortcut Scripts:
* **Windows**: `glb2print.bat model.glb --split-axis x --split-coord 0.0`
* **macOS / Linux**: `./glb2print.sh model.glb --split-axis x --split-coord 0.0`

---

## Configuration & Settings

Settings are automatically persisted in `glb2print_config.json`:
* **Blender Path**: Auto-discovered or customized via the GUI `⚙ Settings` dialog or `--blender-path`.
* **Optional Slicer**: You can link an optional slicer executable (OrcaSlicer, Bambu Studio, PrusaSlicer) in the Settings dialog to open converted files directly.

---

## Windows Explorer Context Menu (Optional)

To enable 1-click conversion directly from Windows Explorer:
1. Right-click `install_context_menu.ps1` and select **Run with PowerShell**.
2. Now, you can right-click any `.glb` or `.gltf` file in Windows Explorer and choose **"Prepare for 3D Printing (GLB2Print)"**.
3. To remove the menu entry, run `uninstall_context_menu.ps1`.

---

## Disclaimer

Blender, Tripo, Meshy, Rodin, OrcaSlicer, Bambu Studio, PrusaSlicer, Creality Print, Cura, and Snapmaker Orca are trademarks of their respective owners. GLB2Print is an independent open-source utility and is not affiliated with or endorsed by any of these projects.

