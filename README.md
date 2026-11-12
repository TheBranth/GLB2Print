# GLB2Print — Universal 3D-Printing Preparation Tool

A fast, cross-platform standalone tool and GUI that converts textured `.glb` / `.gltf` 3D models (such as AI-generated models from Tripo, Meshy, Rodin, or game assets) directly into **3D-printing ready** `.3mf` and `.obj` files with baked vertex colors.

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

## Why Use GLB2Print?

* **No More Manual Blender Baking**: Slicers cannot use UV-mapped 2D texture images for multi-color toolpaths. Normally, you have to manually open Blender, configure materials, bake texture maps to vertex colors, decimate, align to the print bed, and export. **GLB2Print automates this entire process headlessly in seconds.**
* **Texture Resizing Before Baking**: Downscale massive 4K textures (e.g. to 1024×1024 or 512×512) prior to sampling to dramatically speed up conversion and reduce memory overhead without any loss in FDM print quality.
* **Smart Polygon Decimation**: AI models typically come with 1–3 million micro-polygons. GLB2Print includes a quadric decimation engine that preserves silhouette edges and vertex colors while shrinking files from ~200MB down to ~3MB–25MB for lightning-fast slicing.
* **Auto-Ground to Print Bed**: Automatically computes the model's bounding box and shifts the lowest vertex to $Z = 0.0$ so the model sits flat on your build plate.
* **Cross-Platform**: Runs natively on **Windows**, **macOS**, and **Linux** with zero extra UI dependencies (uses Python's built-in Tkinter).

---

## Quickstart (Desktop GUI)

### 1. Launch the GUI
* **Windows**: Double-click `run_gui.bat` (or run `python app_gui.py`).
* **macOS / Linux**: Double-click `run_gui.sh` (or run `python3 app_gui.py`).

### 2. Steps to Convert
1. **Select Model**: Click **Browse File** (or **Batch Folder** to convert an entire directory).
2. **Texture Resolution**: Choose your maximum texture sampling dimension (`Original`, `2048px`, `1024px`, or `512px`).
3. **Polygon Decimation**: Pick a preset (`100k Fast Slicing`, `250k Balanced Sweetspot`, `500k High Detail`) or adjust the slider.
4. **Print Bed Prep**: Check `Auto-ground to print bed (Z = 0)`.
5. **Export Formats**: Check `OBJ` (vertex colors) and/or `3MF` (color groups).
6. Click **⚡ CONVERT FOR 3D PRINTING**.

---

## Command Line Interface (CLI)

GLB2Print includes a full-featured CLI (`cli.py`) for automated terminal workflows, scripts, and batch processing.

### Usage Examples

```bash
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
| `-t` | `--triangles` | `integer` | `250000` | **Target polygon/triangle count**. Decimates mesh while preserving vertex colors. Set to `0` to keep the original mesh. |
| `-r` | `--texture-res` | `integer` | `1024` | **Max texture dimension (px)** before baking (e.g. `512`, `1024`, `2048`). Set to `0` to use full original texture. |
| `-f` | `--format` | `obj`, `3mf`, `both` | `both` | **Export format**: `obj` (vertex-colored OBJ), `3mf` (color-group 3MF), or `both`. |
| `-o` | `--output-dir` | `path` | Input folder | Destination directory for exported files. |
| | `--height-mm` | `float` | `0.0` | Target height in millimeters. Scales model uniformly. `0.0` preserves original model dimensions. |
| | `--no-ground` | `flag` | `False` | Disables auto-grounding. By default, the bottom vertex is shifted to $Z = 0.0$. |
| | `--blender-path` | `path` | Auto-detected | Custom path to the Blender executable. |
| | `--set-blender-default` | `flag` | `False` | Saves the custom `--blender-path` permanently to `glb2print_config.json`. |

### CLI Shortcut Scripts:
* **Windows**: `glb2print.bat model.glb -t 250000 -r 1024`
* **macOS / Linux**: `./glb2print.sh model.glb -t 250000 -r 1024`

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
