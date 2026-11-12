"""
app_gui.py - Modern Cross-Platform Desktop GUI for GLB2Print.
Runs natively on Windows, macOS, and Linux using Python's built-in Tkinter/TTK.
Zero extra dependencies required.
"""

import sys
import os
import threading
import subprocess
import platform
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from config import load_config, save_config, find_blender_binary
from engine.processor import ConversionJob

class GLB2PrintApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("GLB2Print - Universal 3D-Printing Prep")
        self.geometry("720x780")
        self.minsize(640, 700)

        self.cfg = load_config()

        # State Variables
        self.input_files = [] # list of files for single or batch
        self.output_dir_var = tk.StringVar(value="")
        self.export_obj_var = tk.BooleanVar(value=self.cfg.get("default_format") in ("obj", "both"))
        self.export_3mf_var = tk.BooleanVar(value=self.cfg.get("default_format") in ("3mf", "both"))
        self.ground_z_var = tk.BooleanVar(value=self.cfg.get("ground_z", True))
        self.height_mm_var = tk.StringVar(value=str(self.cfg.get("scale_height_mm", 0.0) or ""))

        # Texture Res Slider (0=Original, 512, 1024, 2048, 4096)
        self.texture_res_options = ["Original", "512", "1024", "2048", "4096"]
        default_res = str(self.cfg.get("default_texture_res", 1024))
        self.texture_res_var = tk.StringVar(value=default_res if default_res != "0" else "Original")

        # Decimation
        self.decimate_triangles_var = tk.IntVar(value=self.cfg.get("default_triangles", 250000))
        self.decimate_enable_var = tk.BooleanVar(value=True)

        self.blender_path_var = tk.StringVar(value=self.cfg.get("blender_path", ""))

        self.is_converting = False

        self._configure_styles()
        self._build_ui()
        self._check_blender_health()

    def _configure_styles(self):
        self.style = ttk.Style(self)
        # Use clean theme
        if "clam" in self.style.theme_names():
            self.style.theme_use("clam")

        # Color palette
        bg_main = "#f8f9fa"
        self.configure(bg=bg_main)

        self.style.configure(".", background=bg_main, font=("Segoe UI", 10))
        self.style.configure("Header.TLabel", font=("Segoe UI", 16, "bold"), foreground="#1e293b", background=bg_main)
        self.style.configure("SubHeader.TLabel", font=("Segoe UI", 9), foreground="#64748b", background=bg_main)
        self.style.configure("Card.TFrame", background="#ffffff", relief="flat")
        self.style.configure("CardTitle.TLabel", font=("Segoe UI", 11, "bold"), foreground="#0f172a", background="#ffffff")
        self.style.configure("Desc.TLabel", font=("Segoe UI", 9), foreground="#64748b", background="#ffffff")

        self.style.configure("Primary.TButton", font=("Segoe UI", 11, "bold"), foreground="#ffffff", background="#2563eb", borderwidth=0)
        self.style.map("Primary.TButton", background=[("active", "#1d4ed8"), ("disabled", "#94a3b8")])

        self.style.configure("Secondary.TButton", font=("Segoe UI", 9), background="#e2e8f0", foreground="#1e293b")
        self.style.map("Secondary.TButton", background=[("active", "#cbd5e1")])

    def _build_ui(self):
        main_frame = ttk.Frame(self, padding="16")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 1. Header with Settings Gear
        header_row = ttk.Frame(main_frame)
        header_row.pack(fill=tk.X, pady=(0, 12))

        header_text_frame = ttk.Frame(header_row)
        header_text_frame.pack(side=tk.LEFT, fill=tk.Y)

        title_lbl = ttk.Label(header_text_frame, text="GLB2Print", style="Header.TLabel")
        title_lbl.pack(anchor="w")

        subtitle_lbl = ttk.Label(header_text_frame, text="Turn AI & game GLB models into 3D-printing ready OBJ & 3MF files with baked vertex colors", style="SubHeader.TLabel")
        subtitle_lbl.pack(anchor="w")

        settings_btn = ttk.Button(header_row, text="⚙ Settings", style="Secondary.TButton", command=self._open_settings_dialog)
        settings_btn.pack(side=tk.RIGHT, pady=4)

        # 2. File Selection Card
        file_card = self._create_card(main_frame, "1. Select Model (.glb / .gltf)")
        file_row = ttk.Frame(file_card, style="Card.TFrame")
        file_row.pack(fill=tk.X, padx=12, pady=(0, 8))

        self.file_path_entry = ttk.Entry(file_row, font=("Segoe UI", 9))
        self.file_path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))

        browse_file_btn = ttk.Button(file_row, text="Browse File", style="Secondary.TButton", command=self._browse_file)
        browse_file_btn.pack(side=tk.LEFT, padx=(0, 4))

        browse_batch_btn = ttk.Button(file_row, text="Batch Folder", style="Secondary.TButton", command=self._browse_folder)
        browse_batch_btn.pack(side=tk.LEFT)

        self.file_status_lbl = ttk.Label(file_card, text="No model selected (Drop or browse a .glb)", style="Desc.TLabel")
        self.file_status_lbl.pack(anchor="w", padx=12, pady=(0, 10))

        # 3. Texture Resizing Card (User Request!)
        tex_card = self._create_card(main_frame, "2. Texture Resolution Before Baking")
        tex_desc = ttk.Label(tex_card, text="Resize large 4K textures prior to vertex color baking to drastically speed up processing and lower RAM.", style="Desc.TLabel")
        tex_desc.pack(anchor="w", padx=12, pady=(0, 8))

        tex_row = ttk.Frame(tex_card, style="Card.TFrame")
        tex_row.pack(fill=tk.X, padx=12, pady=(0, 10))

        ttk.Label(tex_row, text="Max Texture Dimension:", background="#ffffff", font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT, padx=(0, 8))

        for opt in self.texture_res_options:
            val_text = f"{opt}px" if opt != "Original" else "Original (No resize)"
            rb = ttk.Radiobutton(tex_row, text=val_text, variable=self.texture_res_var, value=opt)
            rb.pack(side=tk.LEFT, padx=6)

        # 4. Mesh Decimation Card
        dec_card = self._create_card(main_frame, "3. Polygon Decimation (Slicer Optimization)")
        dec_desc = ttk.Label(dec_card, text="AI GLB models often contain millions of micro-polygons. Decimating optimizes slicing speed and keeps colors sharp.", style="Desc.TLabel")
        dec_desc.pack(anchor="w", padx=12, pady=(0, 8))

        dec_row = ttk.Frame(dec_card, style="Card.TFrame")
        dec_row.pack(fill=tk.X, padx=12, pady=(0, 6))

        self.dec_chk = ttk.Checkbutton(dec_row, text="Enable Smart Decimation", variable=self.decimate_enable_var, command=self._toggle_decimate)
        self.dec_chk.pack(side=tk.LEFT, padx=(0, 12))

        self.triangles_scale = ttk.Scale(dec_row, from_=50000, to=1000000, variable=self.decimate_triangles_var, command=self._on_triangles_slider)
        self.triangles_scale.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8)

        self.triangles_lbl = ttk.Label(dec_row, text=f"{self.decimate_triangles_var.get():,} faces", background="#ffffff", font=("Segoe UI", 9, "bold"), width=14)
        self.triangles_lbl.pack(side=tk.LEFT, padx=(4, 0))

        preset_row = ttk.Frame(dec_card, style="Card.TFrame")
        preset_row.pack(anchor="w", padx=12, pady=(0, 10))
        ttk.Label(preset_row, text="Presets:", background="#ffffff", font=("Segoe UI", 8)).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(preset_row, text="100k (Fast Slicing)", style="Secondary.TButton", command=lambda: self._set_triangles(100000)).pack(side=tk.LEFT, padx=3)
        ttk.Button(preset_row, text="250k (Balanced Sweetspot)", style="Secondary.TButton", command=lambda: self._set_triangles(250000)).pack(side=tk.LEFT, padx=3)
        ttk.Button(preset_row, text="500k (High Detail)", style="Secondary.TButton", command=lambda: self._set_triangles(500000)).pack(side=tk.LEFT, padx=3)

        # 5. Print Bed Prep & Output Formats
        opt_card = self._create_card(main_frame, "4. 3D Print Preparation & Export Formats")
        opt_row = ttk.Frame(opt_card, style="Card.TFrame")
        opt_row.pack(fill=tk.X, padx=12, pady=(0, 8))

        ttk.Checkbutton(opt_row, text="Auto-ground to print bed (Z = 0)", variable=self.ground_z_var).pack(side=tk.LEFT, padx=(0, 16))

        ttk.Label(opt_row, text="Target Height (mm, 0=original):", background="#ffffff").pack(side=tk.LEFT, padx=(0, 4))
        self.height_entry = ttk.Entry(opt_row, textvariable=self.height_mm_var, width=8)
        self.height_entry.pack(side=tk.LEFT)

        fmt_row = ttk.Frame(opt_card, style="Card.TFrame")
        fmt_row.pack(fill=tk.X, padx=12, pady=(0, 10))

        ttk.Label(fmt_row, text="Export Formats:", background="#ffffff", font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT, padx=(0, 12))
        ttk.Checkbutton(fmt_row, text="OBJ (.obj with vertex colors)", variable=self.export_obj_var).pack(side=tk.LEFT, padx=(0, 12))
        ttk.Checkbutton(fmt_row, text="3MF (.3mf with color groups)", variable=self.export_3mf_var).pack(side=tk.LEFT)

        # 6. Action Button & Progress
        action_row = ttk.Frame(main_frame)
        action_row.pack(fill=tk.X, pady=(12, 6))

        self.convert_btn = ttk.Button(action_row, text="⚡ CONVERT FOR 3D PRINTING", style="Primary.TButton", command=self._start_conversion)
        self.convert_btn.pack(fill=tk.X, ipady=6)

        self.progress_bar = ttk.Progressbar(main_frame, mode="determinate")
        self.progress_bar.pack(fill=tk.X, pady=(6, 4))

        self.status_lbl = ttk.Label(main_frame, text="Ready", style="SubHeader.TLabel")
        self.status_lbl.pack(anchor="w")

        # 7. Log output area
        log_frame = ttk.Frame(main_frame)
        log_frame.pack(fill=tk.BOTH, expand=True, pady=(8, 0))

        self.log_text = tk.Text(log_frame, height=6, bg="#ffffff", fg="#334155", font=("Consolas", 8), relief="solid", bd=1)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.config(yscrollcommand=scrollbar.set)

    def _create_card(self, parent, title):
        card = ttk.Frame(parent, style="Card.TFrame", padding="8", relief="solid", borderwidth=1)
        card.pack(fill=tk.X, pady=(0, 10))
        lbl = ttk.Label(card, text=title, style="CardTitle.TLabel")
        lbl.pack(anchor="w", padx=12, pady=(4, 6))
        return card

    def _on_triangles_slider(self, val):
        count = int(float(val))
        self.decimate_triangles_var.set(count)
        self.triangles_lbl.config(text=f"{count:,} faces")

    def _set_triangles(self, count):
        self.decimate_enable_var.set(True)
        self.decimate_triangles_var.set(count)
        self.triangles_scale.set(count)
        self.triangles_lbl.config(text=f"{count:,} faces")
        self._toggle_decimate()

    def _toggle_decimate(self):
        state = tk.NORMAL if self.decimate_enable_var.get() else tk.DISABLED
        self.triangles_scale.config(state=state)
        self.triangles_lbl.config(foreground="#000000" if state == tk.NORMAL else "#94a3b8")

    def _browse_file(self):
        filetypes = [("GLB / GLTF 3D Files", "*.glb *.gltf"), ("All Files", "*.*")]
        chosen = filedialog.askopenfilename(title="Select GLB Model", filetypes=filetypes)
        if chosen:
            self.input_files = [chosen]
            self.file_path_entry.delete(0, tk.END)
            self.file_path_entry.insert(0, chosen)
            size_mb = os.path.getsize(chosen) / (1024 * 1024)
            self.file_status_lbl.config(text=f"Selected: {os.path.basename(chosen)} ({size_mb:.2f} MB)")

    def _browse_folder(self):
        folder = filedialog.askdirectory(title="Select Folder with GLB Files")
        if folder:
            glbs = [str(p) for p in Path(folder).glob("*.glb")] + [str(p) for p in Path(folder).glob("*.gltf")]
            if not glbs:
                messagebox.showwarning("No GLB Files", f"No .glb or .gltf files found in {folder}")
                return
            self.input_files = glbs
            self.file_path_entry.delete(0, tk.END)
            self.file_path_entry.insert(0, f"[Batch Folder] {folder} ({len(glbs)} files)")
            self.file_status_lbl.config(text=f"Batch queue: {len(glbs)} models ready for conversion.")

    def _check_blender_health(self):
        b_path = self.blender_path_var.get()
        if not b_path or not os.path.isfile(b_path):
            self._log("Notice: Blender path not set or invalid. Opening settings...")
            self.after(300, self._open_settings_dialog)
        else:
            self._log(f"Blender engine active: {b_path}")

    def _open_settings_dialog(self):
        dlg = tk.Toplevel(self)
        dlg.title("GLB2Print Settings")
        dlg.geometry("540x300")
        dlg.transient(self)
        dlg.grab_set()

        pad = ttk.Frame(dlg, padding="16")
        pad.pack(fill=tk.BOTH, expand=True)

        ttk.Label(pad, text="Blender Executable Path:", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 4))
        ttk.Label(pad, text="Used headlessly to decompress meshopt GLB files, sample textures, and decimate mesh.", foreground="#64748b", font=("Segoe UI", 8)).pack(anchor="w", pady=(0, 6))

        b_row = ttk.Frame(pad)
        b_row.pack(fill=tk.X, pady=(0, 12))

        b_entry = ttk.Entry(b_row, textvariable=self.blender_path_var)
        b_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))

        def browse_blender():
            f = filedialog.askopenfilename(title="Locate Blender Executable")
            if f:
                self.blender_path_var.set(f)

        def auto_detect_blender():
            found = find_blender_binary()
            if found:
                self.blender_path_var.set(found)
                messagebox.showinfo("Auto-Detect", f"Found Blender at:\n{found}")
            else:
                messagebox.showwarning("Auto-Detect", "Could not locate Blender automatically. Please browse manually.")

        ttk.Button(b_row, text="Browse...", command=browse_blender).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(b_row, text="Auto-Detect", command=auto_detect_blender).pack(side=tk.LEFT)

        # Slicer path configuration (Optional)
        ttk.Label(pad, text="Preferred Slicer Executable (Optional):", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(6, 4))
        ttk.Label(pad, text="e.g. Snapmaker Orca, Bambu Studio, or PrusaSlicer (leave blank if not needed).", foreground="#64748b", font=("Segoe UI", 8)).pack(anchor="w", pady=(0, 6))

        s_row = ttk.Frame(pad)
        s_row.pack(fill=tk.X, pady=(0, 16))

        slicer_var = tk.StringVar(value=self.cfg.get("slicer_path", ""))
        s_entry = ttk.Entry(s_row, textvariable=slicer_var)
        s_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))

        def browse_slicer():
            f = filedialog.askopenfilename(title="Locate Slicer Executable")
            if f:
                slicer_var.set(f)
        ttk.Button(s_row, text="Browse...", command=browse_slicer).pack(side=tk.LEFT)

        def save_and_close():
            self.cfg["blender_path"] = self.blender_path_var.get()
            self.cfg["slicer_path"] = slicer_var.get()
            save_config(self.cfg)
            self._log(f"Saved configuration (Blender: {self.cfg['blender_path']})")
            dlg.destroy()

        save_btn = ttk.Button(pad, text="Save Settings", style="Primary.TButton", command=save_and_close)
        save_btn.pack(side=tk.RIGHT, pady=(10, 0))

    def _log(self, msg):
        self.log_text.insert(tk.END, msg + "\n")
        self.log_text.see(tk.END)

    def _start_conversion(self):
        if self.is_converting:
            return

        # Read manual entry if input_files is empty
        entry_text = self.file_path_entry.get().strip()
        if not self.input_files and entry_text and os.path.isfile(entry_text):
            self.input_files = [entry_text]

        if not self.input_files:
            messagebox.showwarning("No File", "Please select a .glb model or folder first.")
            return

        if not self.export_obj_var.get() and not self.export_3mf_var.get():
            messagebox.showwarning("No Format Selected", "Please check at least one export format: OBJ or 3MF.")
            return

        blender_bin = self.blender_path_var.get()
        if not blender_bin or not os.path.isfile(blender_bin):
            messagebox.showerror("Blender Missing", "Blender executable path is missing or invalid. Please check Settings.")
            return

        # Start thread
        self.is_converting = True
        self.convert_btn.config(state=tk.DISABLED)
        self.progress_bar["value"] = 0
        self.log_text.delete("1.0", tk.END)

        thread = threading.Thread(target=self._run_conversion_worker, daemon=True)
        thread.start()

    def _run_conversion_worker(self):
        total_files = len(self.input_files)
        tex_res_str = self.texture_res_var.get()
        tex_res = 0 if tex_res_str == "Original" else int(tex_res_str)

        target_triangles = self.decimate_triangles_var.get() if self.decimate_enable_var.get() else 0
        ground_z = self.ground_z_var.get()

        try:
            h_mm = float(self.height_mm_var.get())
        except ValueError:
            h_mm = 0.0

        successes = 0
        last_out_dir = None

        for idx, file_path in enumerate(self.input_files, 1):
            p = Path(file_path).resolve()
            out_dir = p.parent
            last_out_dir = out_dir
            stem = p.stem

            out_obj = str(out_dir / f"{stem}_print.obj") if self.export_obj_var.get() else None
            out_3mf = str(out_dir / f"{stem}_print.3mf") if self.export_3mf_var.get() else None

            self.after(0, lambda f=p.name, i=idx, t=total_files: self.status_lbl.config(text=f"Processing [{i}/{t}]: {f}"))
            self.after(0, lambda f=p.name: self._log(f"\n--- Starting: {f} ---"))

            def log_cb(msg):
                self.after(0, lambda m=msg: self._log(m))

            def prog_cb(pct, text):
                # Scale progress across all files
                overall = ((idx - 1) / total_files) + (pct / total_files)
                self.after(0, lambda o=overall, t=text: self._update_progress(o, t))

            job = ConversionJob(
                input_glb=str(p),
                output_obj=out_obj,
                output_3mf=out_3mf,
                blender_path=self.blender_path_var.get(),
                texture_res=tex_res,
                target_triangles=target_triangles,
                ground_z=ground_z,
                height_mm=h_mm,
                log_callback=log_cb,
                progress_callback=prog_cb
            )

            ok = job.run()
            if ok:
                successes += 1

        self.after(0, lambda s=successes, t=total_files, d=last_out_dir: self._on_conversion_finished(s, t, d))

    def _update_progress(self, ratio, text):
        self.progress_bar["value"] = int(ratio * 100)
        self.status_lbl.config(text=text)

    def _on_conversion_finished(self, successes, total, out_dir):
        self.is_converting = False
        self.convert_btn.config(state=tk.NORMAL)
        self.progress_bar["value"] = 100
        self.status_lbl.config(text=f"Finished! {successes}/{total} models ready for 3D printing.")
        self._log(f"\n[DONE] Successfully processed {successes}/{total} files.")

        if successes > 0 and messagebox.askyesno("Finished!", f"Successfully converted {successes} model(s)!\n\nOpen output directory in file explorer?"):
            if out_dir and os.path.isdir(out_dir):
                if platform.system() == "Windows":
                    os.startfile(out_dir)
                elif platform.system() == "Darwin":
                    subprocess.Popen(["open", str(out_dir)])
                else:
                    subprocess.Popen(["xdg-open", str(out_dir)])

if __name__ == "__main__":
    app = GLB2PrintApp()
    app.mainloop()
