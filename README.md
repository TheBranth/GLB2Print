# GLB2Print — Universal 3D-Printing Preparation Tool

A fast, cross-platform standalone tool and GUI that converts textured `.glb` / `.gltf` 3D models (such as AI-generated models from Tripo, Meshy, Rodin, or game assets) directly into **3D-printing ready** `.3mf` and `.obj` files with baked vertex colors.

**Compatible with any slicer**: OrcaSlicer, Bambu Studio, PrusaSlicer, Creality Print, Cura, Snapmaker Orca, etc.

---

## Why Use GLB2Print?

* **No More Manual Blender Baking**: Slicers cannot use UV-mapped 2D texture images for multi-color toolpaths. Normally, you have to manually open Blender, configure materials, bake texture maps to vertex colors, decimate, align to the print bed, and export. **GLB2Print automates this entire process headlessly in seconds.**
* **Texture Resizing Before Baking**: Downscale massive 4K textures (e.g. to 1024×1024 or 512×512) prior to sampling to dramatically speed up conversion and reduce memory overhead without any loss in FDM print quality.
* **Smart Polygon Decimation**: AI models typically come with 1–3 million micro-polygons. GLB2Print includes a quadric decimation engine that preserves silhouette edges and vertex colors while shrinking files from ~200MB down to ~3MB–25MB for lightning-fast slicing.
* **Auto-Ground to Print Bed**: Automatically computes the model's bounding box and shifts the lowest vertex to $Z = 0.0$ so the model sits flat on your build plate.
* **Cross-Platform**: Runs natively on **Windows**, **macOS**, and **Linux** with zero extra UI dependencies (uses Python's built-in Tkinter).

---

## Quickstart

### 1. Launch the Desktop GUI

* **Windows**: Double-click `run_gui.bat` (or run `python app_gui.py`).
* **macOS / Linux**: Double-click `run_gui.sh` (or run `python3 app_gui.py`).

### 2. Using the GUI

1. **Select Model**: Click **Browse File** (or **Batch Folder** to convert an entire directory).
2. **Texture Resolution**: Choose your maximum texture sampling dimension (`Original`, `2048px`, `1024px`, or `512px`).
3. **Polygon Decimation**: Pick a preset (`100k Fast Slicing`, `250k Balanced Sweetspot`, `500k High Detail`) or adjust the slider.
4. **Print Bed Prep**: Check `Auto-ground to print bed (Z = 0)`.
5. **Export Formats**: Check `OBJ` (vertex colors) and/or `3MF` (color groups).
6. Click **⚡ CONVERT FOR 3D PRINTING**.

---

## Command Line Interface (CLI)

GLB2Print also features a complete CLI for automated terminal workflows:

```bash
# Convert a single GLB to both OBJ and 3MF with 250k faces and 1024px texture
python cli.py badger.glb -t 250000 -r 1024 -f both

# Convert all models in a folder
python cli.py models/*.glb -o output_prints/ -t 200000

# Keep original mesh without decimation or texture downscaling
python cli.py model.glb -t 0 -r 0

# Set model height to 120 mm
python cli.py model.glb --height-mm 120
```

### CLI Shortcut Scripts:
* **Windows**: `glb2print.bat model.glb -t 250000`
* **macOS / Linux**: `./glb2print.sh model.glb -t 250000`

---

## Configuration & Settings

Settings are automatically saved in `glb2print_config.json`:
* **Blender Path**: GLB2Print auto-detects your local Blender binary on Windows, macOS, and Linux. You can also customize or browse to a specific version in the GUI under `⚙ Settings`.
* **Optional Slicer**: You can link your preferred slicer executable (OrcaSlicer, Bambu Studio, PrusaSlicer) in the Settings dialog.

---

## Windows Explorer Context Menu (Optional)

To enable 1-click conversion right from Windows Explorer:
1. Right-click `install_context_menu.ps1` and select **Run with PowerShell**.
2. Now, you can right-click any `.glb` or `.gltf` file in Windows Explorer and choose **"Prepare for 3D Printing (GLB2Print)"**.
3. To remove the menu item, run `uninstall_context_menu.ps1`.
