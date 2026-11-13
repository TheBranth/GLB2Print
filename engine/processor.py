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

from engine.logger import log_info, log_warn, log_error, log_crash

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
                 plane_point: Optional[str] = None,
                 plane_normal: Optional[str] = None,
                 add_pegs: bool = False,
                 peg_radius: float = 2.0,
                 peg_height: float = 5.0,
                 solidify_mm: float = 0.0,
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
        self.plane_point = plane_point
        self.plane_normal = plane_normal
        self.add_pegs = add_pegs
        self.peg_radius = peg_radius
        self.peg_height = peg_height
        self.solidify_mm = solidify_mm
        self.parts_json = os.path.abspath(parts_json) if parts_json else ""
        self.log_callback = log_callback or (lambda msg: None)
        self.progress_callback = progress_callback or (lambda pct, msg: None)

    def run(self) -> bool:
        """Executes the conversion job. Returns True if successful."""
        log_info(f"=== Starting Conversion Job ===")
        log_info(f"Input GLB: {self.input_glb}")
        log_info(f"Output OBJ: {self.output_obj or 'None'} | Output 3MF: {self.output_3mf or 'None'}")
        log_info(f"Settings: TexRes={self.texture_res}, TargetTris={self.target_triangles}, GroundZ={self.ground_z}")
        if self.parts_json:
            log_info(f"Multi-Part Mode JSON: {self.parts_json}")
        elif self.plane_point and self.plane_normal:
            log_info(f"Planar Cut Mode (Knife Plane): Point={self.plane_point}, Normal={self.plane_normal}, Cap={self.split_cap}, Pegs={self.add_pegs}")
        elif self.split_axis != "none":
            log_info(f"Planar Cut Mode: Axis={self.split_axis}, Coord={self.split_coord}, Cap={self.split_cap}, Pegs={self.add_pegs}")

        if not os.path.isfile(self.input_glb):
            err_msg = f"Input file does not exist: {self.input_glb}"
            log_error(err_msg)
            self.log_callback(err_msg)
            return False

        if not self.blender_path or not os.path.isfile(self.blender_path):
            err_msg = f"Blender executable not found at: {self.blender_path}"
            log_error(err_msg)
            self.log_callback(err_msg)
            return False

        worker_script = Path(__file__).resolve().parent / "blender_worker.py"
        if not worker_script.is_file():
            err_msg = f"Worker script not found at: {worker_script}"
            log_error(err_msg)
            self.log_callback(err_msg)
            return False

        cmd = [
            self.blender_path,
            "-b",
            "--python", str(worker_script),
            "--",
            f"--input={self.input_glb}",
            f"--texture-res={self.texture_res}",
            f"--target-triangles={self.target_triangles}",
            f"--decimate-ratio={self.decimate_ratio}",
            f"--height-mm={self.height_mm}",
            f"--split-axis={self.split_axis}",
            f"--split-coord={self.split_coord}",
        ]

        if not self.split_cap:
            cmd.append("--no-split-cap")

        if self.solidify_mm != 0.0:
            cmd.append(f"--solidify-mm={self.solidify_mm}")

        if self.plane_point and self.plane_normal:
            cmd.extend([f"--plane-point={self.plane_point}", f"--plane-normal={self.plane_normal}"])

        if self.add_pegs:
            cmd.append("--add-pegs")
            cmd.extend([f"--peg-radius={self.peg_radius}", f"--peg-height={self.peg_height}"])

        if self.parts_json:
            cmd.extend([f"--parts-json={self.parts_json}"])

        if self.output_obj:
            cmd.extend([f"--output-obj={self.output_obj}"])
        if self.output_3mf:
            cmd.extend([f"--output-3mf={self.output_3mf}"])
        if self.ground_z:
            cmd.append("--ground-z")

        log_info(f"Executing command: {' '.join(cmd)}")
        self.progress_callback(0.05, "Starting Blender headless worker...")
        self.log_callback(f"Running conversion on: {os.path.basename(self.input_glb)}")

        captured_lines = []
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

                captured_lines.append(line_str)
                log_info(f"[Blender] {line_str}")

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
                elif "Error" in line_str or "Traceback" in line_str or "Exception" in line_str:
                    self.log_callback(line_str)

            process.wait()
            success = (process.returncode == 0)
            if success:
                log_info("Conversion completed successfully (Exit Code 0).")
                self.progress_callback(1.0, "Ready!")
            else:
                tail = "\n".join(captured_lines[-25:])
                log_crash(
                    title=f"Blender worker failed with exit code {process.returncode}",
                    extra_context=f"Last output lines:\n{tail}"
                )
                self.log_callback(f"Blender failed with exit code {process.returncode}")
                self.progress_callback(0.0, f"Failed with exit code {process.returncode}")
            return success

        except Exception as e:
            tail = "\n".join(captured_lines[-25:]) if captured_lines else "No output captured."
            log_crash(
                title=f"Exception during conversion execution: {e}",
                exc=e,
                extra_context=f"Last output lines:\n{tail}"
            )
            self.log_callback(f"Exception during conversion: {e}")
            self.progress_callback(0.0, f"Error: {e}")
            return False
