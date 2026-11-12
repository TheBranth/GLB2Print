"""
app_gui.py - Unified Desktop Launcher for GLB2Print.
Runs the single-page 3D viewport & control deck inside a native desktop window (pywebview)
with automatic fallback to Chrome/Edge --app mode.
"""

import sys
import os
import shutil
import subprocess
import platform
import webbrowser
from pathlib import Path

from viewer.server import UnifiedAppServer

def find_app_browser():
    """Locates Chrome or Edge for dedicated --app mode fallback."""
    system = platform.system()
    if system == "Windows":
        candidates = [
            shutil.which("chrome"),
            shutil.which("msedge"),
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        ]
        for c in candidates:
            if c and os.path.isfile(c):
                return c
    elif system == "Darwin":
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"
        ]
        for c in candidates:
            if os.path.isfile(c):
                return c
    elif system == "Linux":
        candidates = ["google-chrome", "google-chrome-stable", "chromium", "microsoft-edge"]
        for c in candidates:
            w = shutil.which(c)
            if w:
                return w
    return ""

def main():
    # 1. Parse startup file path (from CLI, context menu, or drag & drop onto .bat)
    initial_file = ""
    if len(sys.argv) > 1 and sys.argv[1]:
        cand = os.path.abspath(sys.argv[1])
        if os.path.isfile(cand) and cand.lower().endswith((".glb", ".gltf")):
            initial_file = cand

    # 2. Start Unified Server
    server = UnifiedAppServer(initial_file)
    url = server.start()
    print(f"[GLB2Print] Unified UI running at: {url}")
    if initial_file:
        print(f"[GLB2Print] Loaded initial model: {initial_file}")

    # 3. Launch via pywebview (Native Desktop Window)
    has_webview = False
    try:
        import webview
        has_webview = True
    except Exception as e:
        print(f"[GLB2Print] pywebview unavailable: {e}")

    if has_webview:
        try:
            window_title = f"GLB2Print — 3D-Print Prep & Smart Split"
            if initial_file:
                window_title += f" [{os.path.basename(initial_file)}]"

            window = webview.create_window(
                window_title,
                url,
                width=1280,
                height=840,
                min_size=(880, 640)
            )

            # Clean exit hook on window close
            def on_closed():
                print("[GLB2Print] Window closed by user. Cleanly shutting down...")
                server.stop()

            window.events.closed += on_closed
            webview.start()
            return
        except Exception as e:
            print(f"[GLB2Print] pywebview execution failed: {e}. Falling back to browser app mode...")

    # 4. Fallback: Chrome / Edge --app Mode (Frameless Single Window)
    browser_bin = find_app_browser()
    if browser_bin:
        print(f"[GLB2Print] Launching single-window browser app mode: {browser_bin}")
        cmd = [browser_bin, f"--app={url}", "--window-size=1280,840"]
        try:
            proc = subprocess.Popen(cmd)
            proc.wait()
            server.stop()
            return
        except Exception as e:
            print(f"[GLB2Print] Browser app mode failed: {e}")

    # 5. Ultimate Fallback: System Default Browser
    print("[GLB2Print] Launching default web browser...")
    webbrowser.open(url)

    # Keep alive until heartbeat watchdog triggers
    try:
        while server.is_running:
            import time
            time.sleep(1)
    except KeyboardInterrupt:
        server.stop()

if __name__ == "__main__":
    main()
