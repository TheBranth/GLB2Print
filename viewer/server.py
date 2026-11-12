"""
server.py - Local server coordinator for GLB2Print's unified single-page architecture.
Handles WebGL model streaming, Blender conversions, multi-part lasso splitting,
and clean lifecycle termination.
"""

import os
import sys
import json
import time
import socket
import tempfile
import threading
import subprocess
import platform
import cgi
from pathlib import Path
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from engine.processor import ConversionJob
from engine.logger import log_info, log_warn, log_error, log_crash, get_recent_logs, get_log_path
from config import load_config, save_config

def get_system_specs():
    """Detects total physical RAM in GB and CPU thread count cross-platform."""
    ram_gb = 16.0
    try:
        sys_name = platform.system()
        if sys_name == "Windows":
            import ctypes
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]
            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                ram_gb = stat.ullTotalPhys / (1024 ** 3)
        elif sys_name == "Darwin":
            out = subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True).strip()
            ram_gb = int(out) / (1024 ** 3)
        elif sys_name == "Linux":
            with open("/proc/meminfo", "r") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        ram_gb = int(line.split()[1]) / (1024 ** 2)
                        break
    except Exception:
        pass

    cores = os.cpu_count() or 4
    return ram_gb, cores

def classify_system(ram_gb: float, cores: int) -> dict:
    """
    Classifies system performance tier and provides educated processing estimates:
    - monster: >= 31GB RAM & >= 12 cores (High-end workstations)
    - standard: >= 15GB RAM & >= 6 cores (Capable desktop/laptop)
    - mid_low: >= 7.5GB RAM (Budget PCs)
    - chromebook: < 7.5GB RAM or <= 2 cores (Chromebooks, low-power netbooks)
    """
    if ram_gb >= 31.0 and cores >= 12:
        return {
            "tier": "monster",
            "tier_label": "⚡ Workstation Beast",
            "specs_label": f"{ram_gb:.0f}GB RAM · {cores} Cores",
            "color": "#4ade80",
            "estimate_speed": "ultra_fast",
            "watchdog_seconds": 900,
            "banner_type": "success",
            "banner_msg": "Workstation beast detected. High-poly models (~1.5M+ faces) will process in ~10–25s."
        }
    elif ram_gb >= 15.0 and cores >= 6:
        return {
            "tier": "standard",
            "tier_label": "💻 Standard PC",
            "specs_label": f"{ram_gb:.0f}GB RAM · {cores} Cores",
            "color": "#38bdf8",
            "estimate_speed": "moderate",
            "watchdog_seconds": 900,
            "banner_type": "info",
            "banner_msg": "Solid system detected. Processing high-poly models typically takes ~30–75s."
        }
    elif ram_gb >= 7.5:
        return {
            "tier": "mid_low",
            "tier_label": "🐌 Budget PC",
            "specs_label": f"{ram_gb:.1f}GB RAM · {cores} Cores",
            "color": "#fbbf24",
            "estimate_speed": "slow",
            "watchdog_seconds": 1200,
            "banner_type": "warning",
            "banner_msg": "Moderate hardware. Heavy models (1M+ faces) may take 2–5 minutes. Decimation is recommended!"
        }
    else:
        return {
            "tier": "chromebook",
            "tier_label": "⚠️ Low-Power / Chromebook",
            "specs_label": f"{ram_gb:.1f}GB RAM · {cores} Cores",
            "color": "#f87171",
            "estimate_speed": "very_slow",
            "watchdog_seconds": 1800,
            "banner_type": "danger",
            "banner_msg": "⚠️ Low-spec device detected! Processing 1M+ face models will take a LOOOONG time (5–15+ minutes). Please enable Decimation!"
        }

class UnifiedAppServer:
    def __init__(self, initial_glb: str = ""):
        self.cfg = load_config()
        self.glb_path = os.path.abspath(initial_glb) if (initial_glb and os.path.isfile(initial_glb)) else ""
        self.viewer_dir = Path(__file__).resolve().parent
        self.port = self._find_free_port()
        self.httpd = None
        self.thread = None
        self.last_heartbeat = time.time()
        self.is_running = True
        self.is_converting = False

        self.ram_gb, self.cores = get_system_specs()
        self.system_info = classify_system(self.ram_gb, self.cores)
        self.watchdog_timeout = self.system_info["watchdog_seconds"]
        log_info(f"System detected: {self.system_info['specs_label']} ({self.system_info['tier_label']}). Adaptive idle watchdog: {self.watchdog_timeout}s.")

    def _find_free_port(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(('127.0.0.1', 0))
        port = s.getsockname()[1]
        s.close()
        return port

    def start(self):
        parent_self = self

        class UnifiedHandler(SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(parent_self.viewer_dir), **kwargs)

            def log_message(self, format, *args):
                pass

            def do_GET(self):
                parent_self.last_heartbeat = time.time()

                if self.path == "/" or self.path == "/index.html":
                    self.path = "/index.html"
                    return super().do_GET()

                elif self.path == "/api/heartbeat":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain")
                    self.end_headers()
                    self.wfile.write(b"OK")
                    return

                elif self.path == "/api/system_specs":
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps(parent_self.system_info).encode("utf-8"))
                    return

                elif self.path == "/api/logs":
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        "logs": get_recent_logs(300),
                        "log_path": str(get_log_path())
                    }).encode("utf-8"))
                    return

                elif self.path == "/api/config":
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps(parent_self.cfg).encode("utf-8"))
                    return

                elif self.path == "/api/model_info":
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    has_m = bool(parent_self.glb_path and os.path.isfile(parent_self.glb_path))
                    fname = os.path.basename(parent_self.glb_path) if has_m else ""
                    self.wfile.write(json.dumps({"has_model": has_m, "filename": fname}).encode("utf-8"))
                    return

                elif self.path == "/api/model.glb":
                    if not parent_self.glb_path or not os.path.isfile(parent_self.glb_path):
                        self.send_error(404, "No active GLB model found")
                        return
                    self.send_response(200)
                    self.send_header("Content-Type", "model/gltf-binary")
                    self.send_header("Content-Length", str(os.path.getsize(parent_self.glb_path)))
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    with open(parent_self.glb_path, "rb") as f:
                        while chunk := f.read(65536):
                            self.wfile.write(chunk)
                    return

                return super().do_GET()

            def do_POST(self):
                parent_self.last_heartbeat = time.time()

                if self.path == "/api/shutdown":
                    self.send_response(200)
                    self.end_headers()
                    parent_self.stop()
                    return

                elif self.path == "/api/open_folder":
                    content_length = int(self.headers.get("Content-Length", 0))
                    data = json.loads(self.rfile.read(content_length).decode("utf-8"))
                    folder = data.get("folder", "")
                    if folder and os.path.isdir(folder):
                        if platform.system() == "Windows":
                            os.startfile(folder)
                        elif platform.system() == "Darwin":
                            subprocess.Popen(["open", folder])
                        else:
                            subprocess.Popen(["xdg-open", folder])
                    self.send_response(200)
                    self.end_headers()
                    return

                elif self.path == "/api/open_log":
                    log_file = str(get_log_path())
                    if os.path.isfile(log_file):
                        if platform.system() == "Windows":
                            os.startfile(log_file)
                        elif platform.system() == "Darwin":
                            subprocess.Popen(["open", log_file])
                        else:
                            subprocess.Popen(["xdg-open", log_file])
                    self.send_response(200)
                    self.end_headers()
                    return

                elif self.path == "/api/config":
                    content_length = int(self.headers.get("Content-Length", 0))
                    data = json.loads(self.rfile.read(content_length).decode("utf-8"))
                    parent_self.cfg.update(data)
                    save_config(parent_self.cfg)
                    self.send_response(200)
                    self.end_headers()
                    return

                elif self.path == "/api/upload":
                    # Handle multipart/form-data upload from drag & drop
                    ctype, pdict = cgi.parse_header(self.headers.get('content-type'))
                    if ctype == 'multipart/form-data':
                        pdict['boundary'] = bytes(pdict['boundary'], "utf-8")
                        fields = cgi.parse_multipart(self.rfile, pdict)
                        file_data = fields.get('model', [None])[0]
                        if file_data:
                            temp_dir = tempfile.gettempdir()
                            dest = os.path.join(temp_dir, f"uploaded_{int(time.time())}.glb")
                            with open(dest, "wb") as f:
                                f.write(file_data)
                            parent_self.glb_path = dest
                            self.send_response(200)
                            self.send_header("Content-Type", "application/json")
                            self.end_headers()
                            self.wfile.write(json.dumps({"success": True}).encode("utf-8"))
                            return

                    self.send_response(400)
                    self.end_headers()
                    return

                elif self.path == "/api/convert":
                    parent_self.is_converting = True
                    parent_self.last_heartbeat = time.time()
                    temp_json = None
                    try:
                        content_length = int(self.headers.get("Content-Length", 0))
                        data = json.loads(self.rfile.read(content_length).decode("utf-8"))

                        p = Path(parent_self.glb_path)
                        out_dir = p.parent
                        stem = p.stem

                        fmt = data.get("format", "both")
                        out_obj = str(out_dir / f"{stem}.obj") if fmt in ("obj", "both") else None
                        out_3mf = str(out_dir / f"{stem}.3mf") if fmt in ("3mf", "both") else None

                        split_mode = data.get("split_mode", "none")
                        split_axis = data.get("split_axis", "none")
                        split_coord = float(data.get("split_coord", 0.0))
                        cap_cut = bool(data.get("cap_cut", True))
                        parts_data = data.get("parts", None)

                        if split_mode == "lasso" and parts_data:
                            with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json", encoding="utf-8") as tf:
                                json.dump(parts_data, tf)
                                temp_json = tf.name

                        job = ConversionJob(
                            input_glb=parent_self.glb_path,
                            output_obj=out_obj,
                            output_3mf=out_3mf,
                            blender_path=parent_self.cfg.get("blender_path"),
                            texture_res=int(data.get("texture_res", 1024)),
                            target_triangles=int(data.get("target_triangles", 250000)),
                            ground_z=bool(data.get("ground_z", True)),
                            split_axis=split_axis if split_mode == "planar" else "none",
                            split_coord=split_coord,
                            split_cap=cap_cut,
                            parts_json=temp_json
                        )

                        ok = job.run()

                        if temp_json:
                            try:
                                os.remove(temp_json)
                            except Exception:
                                pass

                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        resp = {
                            "success": ok,
                            "output_folder": str(out_dir),
                            "error": None if ok else "Blender processing failed. Check logs for details."
                        }
                        self.wfile.write(json.dumps(resp).encode("utf-8"))
                        return
                    except Exception as e:
                        if temp_json:
                            try:
                                os.remove(temp_json)
                            except Exception:
                                pass
                        log_crash("Unhandled server exception in /api/convert", exc=e)
                        self.send_response(500)
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode("utf-8"))
                        return
                    finally:
                        parent_self.is_converting = False
                        parent_self.last_heartbeat = time.time()

                self.send_error(404, "Endpoint not found")

        self.httpd = ThreadingHTTPServer(('127.0.0.1', self.port), UnifiedHandler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

        # Watchdog thread for clean termination
        def watchdog():
            while self.is_running:
                time.sleep(2)
                # Never terminate server while active conversion job is running
                if self.is_converting:
                    self.last_heartbeat = time.time()
                    continue
                # If no heartbeat for > watchdog_timeout, shutdown
                if time.time() - self.last_heartbeat > self.watchdog_timeout:
                    log_warn(f"Watchdog timeout triggered (no heartbeat for {int(time.time() - self.last_heartbeat)}s > {self.watchdog_timeout}s). Stopping server...")
                    self.stop()
                    break
        threading.Thread(target=watchdog, daemon=True).start()

        return f"http://127.0.0.1:{self.port}"

    def stop(self):
        self.is_running = False
        if self.httpd:
            threading.Thread(target=self.httpd.shutdown).start()
        # Clean process termination
        threading.Timer(0.5, lambda: os._exit(0)).start()
