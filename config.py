"""
config.py - Cross-platform configuration and Blender path discovery.
Compatible with Windows, macOS, and Linux.
"""

import os
import sys
import json
import shutil
import platform
from pathlib import Path

CONFIG_FILENAME = "glb2print_config.json"

def get_config_path():
    """Returns path to the configuration file (local to script or in user home)."""
    local_path = Path(__file__).resolve().parent / CONFIG_FILENAME
    return local_path

def find_blender_binary():
    """
    Auto-detects the Blender executable across Windows, macOS, and Linux.
    """
    # 1. Check if 'blender' is already on PATH
    which_blender = shutil.which("blender")
    if which_blender and os.path.isfile(which_blender):
        return which_blender

    system = platform.system()

    # 2. Windows known locations
    if system == "Windows":
        candidates = [
            r"D:\Blender\blender.exe",
            r"C:\Program Files\Blender Foundation\Blender\blender.exe",
            r"C:\Blender\blender.exe",
            r"C:\Program Files (x86)\Blender Foundation\Blender\blender.exe",
        ]
        # Check versioned directories like "Blender 4.2", "Blender 5.2", etc.
        program_files = [os.environ.get("ProgramFiles", r"C:\Program Files"),
                         os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                         r"C:\\", r"D:\\"]
        for pf in program_files:
            bf_dir = Path(pf) / "Blender Foundation"
            if bf_dir.exists():
                for sub in bf_dir.iterdir():
                    b_exe = sub / "blender.exe"
                    if b_exe.exists():
                        candidates.insert(0, str(b_exe))
            # Also check direct D:\Blender or C:\Blender
            direct_b = Path(pf) / "Blender" / "blender.exe"
            if direct_b.exists():
                candidates.insert(0, str(direct_b))

        for cand in candidates:
            if os.path.isfile(cand):
                return cand

    # 3. macOS known locations
    elif system == "Darwin":
        candidates = [
            "/Applications/Blender.app/Contents/MacOS/Blender",
            "~/Applications/Blender.app/Contents/MacOS/Blender",
            "/opt/homebrew/bin/blender",
            "/usr/local/bin/blender"
        ]
        for cand in candidates:
            exp = os.path.expanduser(cand)
            if os.path.isfile(exp):
                return exp

    # 4. Linux known locations
    elif system == "Linux":
        candidates = [
            "/usr/bin/blender",
            "/usr/local/bin/blender",
            "/snap/bin/blender",
            "~/.local/bin/blender"
        ]
        for cand in candidates:
            exp = os.path.expanduser(cand)
            if os.path.isfile(exp):
                return exp

    return ""

DEFAULT_CONFIG = {
    "blender_path": "",
    "default_format": "obj",        # "obj" (vertex colors)
    "default_texture_res": 0,       # 0 = original, 512, 1024, 2048
    "default_triangles": 250000,    # 0 = no decimation
    "ground_z": True,
    "scale_height_mm": 0.0,         # 0.0 = keep original
    "slicer_path": "",              # optional slicer executable path (Orca, Bambu, Prusa)
    "auto_open_slicer": False
}

def load_config():
    """Loads configuration, initializing with auto-detected Blender path if empty."""
    cfg = DEFAULT_CONFIG.copy()
    cfg_file = get_config_path()

    if cfg_file.exists():
        try:
            with open(cfg_file, "r", encoding="utf-8") as f:
                saved = json.load(f)
                cfg.update(saved)
        except Exception:
            pass

    # If blender_path is empty or invalid, try to discover it
    if not cfg.get("blender_path") or not os.path.isfile(cfg["blender_path"]):
        discovered = find_blender_binary()
        if discovered:
            cfg["blender_path"] = discovered
            save_config(cfg)

    return cfg

def save_config(cfg):
    """Saves configuration to disk."""
    cfg_file = get_config_path()
    try:
        with open(cfg_file, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=4)
        return True
    except Exception as e:
        print(f"Error saving config: {e}")
        return False
