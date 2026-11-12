"""
server.py - Local server and viewer launcher for 3D visual representation and planar cut.
Supports pywebview (native window) with fallback to default web browser.
"""

import os
import sys
import json
import socket
import threading
import webbrowser
from pathlib import Path
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from engine.processor import ConversionJob

class ModelViewerServer:
    def __init__(self, glb_path: str, cfg: dict):
        self.glb_path = os.path.abspath(glb_path)
        self.cfg = cfg
        self.viewer_dir = Path(__file__).resolve().parent
        self.port = self._find_free_port()
        self.httpd = None
        self.thread = None

    def _find_free_port(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(('127.0.0.1', 0))
        port = s.getsockname()[1]
        s.close()
        return port

    def start(self):
        parent_self = self

        class ViewerHandler(SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(parent_self.viewer_dir), **kwargs)

            def log_message(self, format, *args):
                # Suppress normal HTTP logging
                pass

            def do_GET(self):
                if self.path == "/" or self.path == "/index.html":
                    self.path = "/index.html"
                    return super().do_GET()
                elif self.path == "/api/model.glb":
                    # Stream the GLB model
                    if not os.path.isfile(parent_self.glb_path):
                        self.send_error(404, "GLB file not found")
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
                if self.path == "/api/split":
                    content_length = int(self.headers.get("Content-Length", 0))
                    body = self.rfile.read(content_length).decode("utf-8")
                    data = json.loads(body)

                    axis = data.get("axis", "x")
                    coord = float(data.get("coord", 0.0))
                    cap_cut = bool(data.get("cap_cut", True))

                    p = Path(parent_self.glb_path)
                    out_dir = p.parent
                    stem = p.stem

                    out_obj = str(out_dir / f"{stem}.obj") if parent_self.cfg.get("default_format") in ("obj", "both") else None
                    out_3mf = str(out_dir / f"{stem}.3mf") if parent_self.cfg.get("default_format") in ("3mf", "both") else None

                    job = ConversionJob(
                        input_glb=parent_self.glb_path,
                        output_obj=out_obj,
                        output_3mf=out_3mf,
                        blender_path=parent_self.cfg.get("blender_path"),
                        texture_res=parent_self.cfg.get("default_texture_res", 1024),
                        target_triangles=parent_self.cfg.get("default_triangles", 250000),
                        ground_z=parent_self.cfg.get("ground_z", True),
                        split_axis=axis,
                        split_coord=coord,
                        split_cap=cap_cut
                    )

                    ok = job.run()

                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    resp = {
                        "success": ok,
                        "output_folder": str(out_dir),
                        "part1_obj": str(out_dir / f"{stem}_part1.obj"),
                        "part2_obj": str(out_dir / f"{stem}_part2.obj")
                    }
                    self.wfile.write(json.dumps(resp).encode("utf-8"))
                    return

                self.send_error(404, "Unknown API endpoint")

        self.httpd = ThreadingHTTPServer(('127.0.0.1', self.port), ViewerHandler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        return f"http://127.0.0.1:{self.port}"

    def stop(self):
        if self.httpd:
            self.httpd.shutdown()

def launch_viewer(glb_path: str, cfg: dict):
    """
    Launches the 3D visual viewer with planar cut tools.
    Attempts pywebview native window first, falls back to web browser.
    """
    server = ModelViewerServer(glb_path, cfg)
    url = server.start()

    has_webview = False
    try:
        import webview
        has_webview = True
    except Exception:
        has_webview = False

    if has_webview:
        try:
            window_title = f"GLB2Print — 3D Viewer & Smart Split [{os.path.basename(glb_path)}]"
            webview.create_window(window_title, url, width=1180, height=820, min_size=(800, 600))
            webview.start()
            server.stop()
            return
        except Exception as e:
            print(f"pywebview start failed, falling back to browser: {e}")

    # Fallback to browser
    webbrowser.open(url)

if __name__ == "__main__":
    if len(sys.argv) > 1:
        test_file = sys.argv[1]
    else:
        test_file = "badger.glb"
    from config import load_config
    cfg = load_config()
    launch_viewer(test_file, cfg)
