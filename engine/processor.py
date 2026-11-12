"""
processor.py - Subprocess coordinator that runs the headless Blender worker
and streams output logs and progress. Cross-platform (Windows, macOS, Linux).
"""

import os
import sys
import subprocess
import threading
from pathlib import Path
from typing import Callable, Optional

class ConversionJob:
    def __init__(self,
                 input_glb: str,
                 output_obj: Optional[str] = None,
                 output_3mf: Optional[str] = None,
                 blender_path: Optional[str] = None,
                 texture_res: int = 1024,
                 target_triangles: int = 250000,
                 decimate_ratio: float = 1.0,
                 ground_z: bool = True,
                 height_mm: float = 0.0,
                 split_axis: str = "none",
                 split_coord: float = 0.0,
                 split_cap: bool = True,
                 parts_json: Optional[str] = None,
                 log_callback: Optional[Callable[[str], None]] = None,
                 progress_callback: Optional[Callable[[float, str], None]] = None):
        self.input_glb = os.path.abspath(input_glb)
        self.output_obj = os.path.abspath(output_obj) if output_obj else ""
        self.output_3mf = os.path.abspath(output_3mf) if output_3mf else ""
        self.blender_path = blender_path
        self.texture_res = texture_res
        self.target_triangles = target_triangles
        self.decimate_ratio = decimate_ratio
        self.ground_z = ground_z
        self.height_mm = height_mm
        self.split_axis = split_axis.lower()
        self.split_coord = split_coord
        self.split_cap = split_cap
        self.parts_json = os.path.abspath(parts_json) if parts_json else ""
        self.log_callback = log_callback or (lambda msg: print(msg))
        self.progress_callback = progress_callback or (lambda pct, msg: None)

    def run(self) -> bool:
        """Executes the conversion job. Returns True if successful."""
        if not os.path.isfile(self.input_glb):
            self.log_callback(f"Error: Input file does not exist: {self.input_glb}")
            return False

        if not self.blender_path or not os.path.isfile(self.blender_path):
            self.log_callback("Error: Blender executable not found. Please configure the Blender path.")
            return False

        worker_script = Path(__file__).resolve().parent / "blender_worker.py"
        if not worker_script.is_file():
            self.log_callback(f"Error: Worker script not found at {worker_script}")
            return False

        cmd = [
            self.blender_path,
            "-b",
            "--python", str(worker_script),
            "--",
            "--input", self.input_glb,
            "--texture-res", str(self.texture_res),
            "--target-triangles", str(self.target_triangles),
            "--decimate-ratio", str(self.decimate_ratio),
            "--height-mm", str(self.height_mm),
            "--split-axis", self.split_axis,
            "--split-coord", str(self.split_coord),
        ]

        if not self.split_cap:
            cmd.append("--no-split-cap")

        if self.parts_json:
            cmd.extend(["--parts-json", self.parts_json])

        if self.output_obj:
            cmd.extend(["--output-obj", self.output_obj])
        if self.output_3mf:
            cmd.extend(["--output-3mf", self.output_3mf])
        if self.ground_z:
            cmd.append("--ground-z")

        self.progress_callback(0.05, "Starting Blender headless worker...")
        self.log_callback(f"Running conversion on: {os.path.basename(self.input_glb)}")

        try:
            creationflags = 0
            if sys.platform == "win32":
                creationflags = subprocess.CREATE_NO_WINDOW

            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=creationflags
            )

            for line in process.stdout:
                line_str = line.strip()
                if not line_str:
                    continue

                if "[GLB2PRINT-WORKER]" in line_str:
                    msg = line_str.replace("[GLB2PRINT-WORKER]", "").strip()
                    self.log_callback(msg)

                    if "GLTF imported" in msg:
                        self.progress_callback(0.20, "Model imported...")
                    elif "Resizing texture" in msg:
                        self.progress_callback(0.30, "Resizing texture...")
                    elif "Baking texture" in msg:
                        self.progress_callback(0.40, "Baking vertex colors...")
                    elif "Color baking completed" in msg:
                        self.progress_callback(0.55, "Colors baked to vertices.")
                    elif "Extracting part" in msg:
                        self.progress_callback(0.70, msg)
                    elif "Decimating mesh" in msg:
                        self.progress_callback(0.75, "Decimating polygons...")
                    elif "Decimation done" in msg:
                        self.progress_callback(0.80, "Decimation complete.")
                    elif "PLANAR CUT" in msg:
                        self.progress_callback(0.80, "Bisecting model along plane...")
                    elif "Building 3MF" in msg or "Exporting Part" in msg:
                        self.progress_callback(0.88, "Packaging parts...")
                    elif "Exported OBJ" in msg or "Exported 3MF" in msg:
                        self.progress_callback(0.95, "Writing 3D print files...")
                    elif "ALL DONE" in msg:
                        self.progress_callback(1.0, "Conversion complete!")
                elif "Error" in line_str or "Traceback" in line_str:
                    self.log_callback(line_str)

            process.wait()
            success = (process.returncode == 0)
            if success:
                self.progress_callback(1.0, "Ready!")
            else:
                self.progress_callback(0.0, f"Failed with exit code {process.returncode}")
            return success

        except Exception as e:
            self.log_callback(f"Exception during conversion: {e}")
            self.progress_callback(0.0, "Error encountered")
            return False
