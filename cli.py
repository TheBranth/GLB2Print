"""
cli.py - Command Line Interface for GLB2Print.
Cross-platform tool to turn GLB 3D models into 3D-printing ready OBJ & 3MF files,
with Smart Splitting (Planar Cut) and 3D Visual Preview.
"""

import sys
import os
import glob
import argparse
from pathlib import Path
from config import load_config, save_config
from engine.processor import ConversionJob

def parse_args():
    parser = argparse.ArgumentParser(
        description="GLB2Print: Convert GLB files into 3D-printing ready OBJ & 3MF with baked vertex colors & smart splitting."
    )
    parser.add_argument("inputs", nargs="+", help="Input GLB file(s) or glob pattern (e.g. model.glb or models/*.glb)")
    parser.add_argument("-o", "--output-dir", default="", help="Output directory (default: same folder as input)")
    parser.add_argument("-f", "--format", choices=["obj", "3mf", "both"], default="both", help="Export format (default: both)")
    parser.add_argument("-t", "--triangles", type=int, default=250000, help="Target triangle count (default: 250000, 0 = keep original)")
    parser.add_argument("-r", "--texture-res", type=int, default=1024, help="Max texture dimension before baking (e.g. 512, 1024, 2048, 0=original)")
    parser.add_argument("--no-ground", action="store_true", help="Do not ground bottom of model to Z=0")
    parser.add_argument("--height-mm", type=float, default=0.0, help="Target height in mm (0 = preserve model scale)")
    parser.add_argument("--blender-path", default="", help="Custom path to Blender executable")
    parser.add_argument("--set-blender-default", action="store_true", help="Save the provided Blender path as default")

    # Planar Cut / Smart Splitting arguments
    parser.add_argument("--split-axis", choices=["none", "x", "y", "z"], default="none", help="Cut plane normal axis (x, y, z)")
    parser.add_argument("--split-coord", type=float, default=0.0, help="Plane position along split axis")
    parser.add_argument("--no-split-cap", action="store_true", help="Do not cap/fill cut holes (keep open)")
    parser.add_argument("--parts-json", default="", help="Path to JSON file specifying multi-part face index mapping")
    parser.add_argument("--preview", action="store_true", help="Open interactive 3D visual preview & planar cut tool")

    return parser.parse_args()

def main():
    args = parse_args()
    cfg = load_config()

    blender_bin = args.blender_path or cfg.get("blender_path", "")
    if args.blender_path and args.set_blender_default:
        cfg["blender_path"] = args.blender_path
        save_config(cfg)
        print(f"[Config] Saved default Blender path: {args.blender_path}")

    # Collect input files
    all_files = []
    for pattern in args.inputs:
        matched = glob.glob(pattern)
        if matched:
            all_files.extend(matched)
        elif os.path.isfile(pattern):
            all_files.append(pattern)

    all_files = [f for f in all_files if f.lower().endswith((".glb", ".gltf"))]

    if not all_files:
        print("No valid .glb or .gltf files found for inputs:", args.inputs)
        sys.exit(1)

    # If --preview is requested, launch the 3D visual viewer on the first model
    if args.preview:
        from viewer.server import launch_viewer
        print(f"Launching 3D Visual Preview for: {all_files[0]}")
        launch_viewer(all_files[0], cfg)
        return

    if not blender_bin or not os.path.isfile(blender_bin):
        print("ERROR: Blender executable not found!")
        print("Please provide it via --blender-path <path> or run the GUI to configure it.")
        sys.exit(1)

    print(f"=== GLB2Print CLI ===")
    print(f"Files to convert: {len(all_files)}")
    print(f"Blender: {blender_bin}")
    print(f"Format: {args.format}")
    print(f"Target triangles: {args.triangles if args.triangles > 0 else 'Original'}")
    print(f"Texture max res: {f'{args.texture_res}px' if args.texture_res > 0 else 'Original'}")
    print(f"Ground to Z=0: {not args.no_ground}")
    if args.split_axis != "none":
        print(f"Smart Split: Axis={args.split_axis.upper()}, Coord={args.split_coord:.3f}, Cap={not args.no_split_cap}")
    print("=" * 22)

    success_count = 0
    for idx, filepath in enumerate(all_files, 1):
        p = Path(filepath).resolve()
        out_dir = Path(args.output_dir).resolve() if args.output_dir else p.parent
        out_dir.mkdir(parents=True, exist_ok=True)

        stem = p.stem
        out_obj = str(out_dir / f"{stem}.obj") if args.format in ("obj", "both") else None
        out_3mf = str(out_dir / f"{stem}.3mf") if args.format in ("3mf", "both") else None

        print(f"\n[{idx}/{len(all_files)}] Processing: {p.name}")
        job = ConversionJob(
            input_glb=str(p),
            output_obj=out_obj,
            output_3mf=out_3mf,
            blender_path=blender_bin,
            texture_res=args.texture_res,
            target_triangles=args.triangles,
            ground_z=(not args.no_ground),
            height_mm=args.height_mm,
            split_axis=args.split_axis,
            split_coord=args.split_coord,
            split_cap=(not args.no_split_cap),
            parts_json=args.parts_json,
            log_callback=lambda msg: print(f"  > {msg}")
        )

        ok = job.run()
        if ok:
            success_count += 1
            print(f"  [OK] Saved to: {out_dir}")
        else:
            print(f"  [FAILED] Failed to convert {p.name}")

    print(f"\nCompleted: {success_count}/{len(all_files)} files converted successfully.")

if __name__ == "__main__":
    main()
