
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import os
import shutil
import sys
import ctypes
import subprocess
import logging

# ---------------- Utilities ----------------
def run_silent():
    script = os.path.abspath("FileMoverApp.py")
    subprocess.Popen(["pythonw", script])

def run_as_admin():
    if ctypes.windll.shell32.IsUserAnAdmin():
        return True
    else:
        script = os.path.abspath(sys.argv[0])
        params = " ".join([f'"{arg}"' for arg in sys.argv[1:]])
        try:
            ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, f'"{script}" {params}', None, 1)
            sys.exit()
        except Exception as e:
            print("Elevation failed:", e)
            return False
    return False


# ---------------- App ----------------
class FileMoverApp:
    def __init__(self, root):
        self.root = root
        self.root.title("File Mover")
        self.root.geometry("450x540")
        self.root.resizable(False, False)

        self.logger = logging.getLogger("file_mover")

        # Paths
        self.src_folder = ""
        self.dst_folder = ""

        # File types (checkboxes)
        self.file_types = [
            ".png", ".ico", ".svg",
            ".csv", ".jpg", ".jpeg", ".xlsx", ".pdf", ".txt",
            ".docx", ".py", ".mp4", ".xls", ".pptx", ".xlsm",
            ".zip", ".rar", ".7z"
        ]
        self.ext_vars = {
            ext: tk.BooleanVar(value=(ext in {".png", ".ico", ".svg"}))
            for ext in self.file_types
        }

        # Options
        self.var_preserve = tk.BooleanVar(value=False)
        self.var_delete = tk.BooleanVar(value=False)
        self.var_silent = tk.BooleanVar(value=True)

        # Logging options (from previous code concept)
        self.var_log_level = tk.StringVar(value="INFO")
        self.var_log_to_file = tk.BooleanVar(value=False)
        self.var_log_path = tk.StringVar(value="")

        self._build_ui()
        self._apply_logging_config()  # initialize logging handlers

        # React to logging option changes
        self.var_log_level.trace_add("write", lambda *_: self._apply_logging_config())
        self.var_log_to_file.trace_add("write", lambda *_: self._on_log_to_file_toggle())
        # Apply when path changes and file logging is on
        self.var_log_path.trace_add("write", lambda *_: self._apply_logging_config() if self.var_log_to_file.get() else None)

    # ---------------- UI ----------------
    def _build_ui(self):
        root = self.root

        # --- Paths ---
        lf_paths = ttk.LabelFrame(root, text="Paths")
        lf_paths.pack(fill="x", padx=10, pady=(10, 6))

        # Source
        row = ttk.Frame(lf_paths)
        row.pack(fill="x", padx=8, pady=4)
        ttk.Label(row, text="Source Folder:", width=16).pack(side="left")
        self.src_lbl = ttk.Label(row, text="Not selected", foreground="#666")
        self.src_lbl.pack(side="left", padx=(6, 8))
        ttk.Button(row, text="Browse", command=self.select_source).pack(side="left")

        # Destination
        row = ttk.Frame(lf_paths)
        row.pack(fill="x", padx=8, pady=4)
        ttk.Label(row, text="Destination:", width=16).pack(side="left")
        self.dst_lbl = ttk.Label(row, text="Not selected", foreground="#666")
        self.dst_lbl.pack(side="left", padx=(6, 8))
        ttk.Button(row, text="Browse", command=self.select_destination).pack(side="left")

        # --- File Types ---
        lf_types = ttk.LabelFrame(root, text="File Types (extensions)")
        lf_types.pack(fill="x", padx=10, pady=6)

        grid = ttk.Frame(lf_types)
        grid.pack(anchor="w", padx=8, pady=6)
        cols = 6
        for i, ext in enumerate(self.file_types):
            r, c = divmod(i, cols)
            ttk.Checkbutton(grid, text=ext, variable=self.ext_vars[ext]).grid(row=r, column=c, sticky="w", padx=6, pady=2)

        # --- Options ---
        lf_opts = ttk.LabelFrame(root, text="Options")
        lf_opts.pack(fill="x", padx=10, pady=6)

        row = ttk.Frame(lf_opts); row.pack(anchor="w", padx=8, pady=(6, 2))
        ttk.Checkbutton(row, text="Preserve folder structure", variable=self.var_preserve).pack(side="left")

        row = ttk.Frame(lf_opts); row.pack(anchor="w", padx=8, pady=2)
        ttk.Checkbutton(row, text="Delete after move", variable=self.var_delete).pack(side="left")

        row = ttk.Frame(lf_opts); row.pack(anchor="w", padx=8, pady=(2, 6))
        ttk.Checkbutton(row, text="Run silent (no popups)", variable=self.var_silent).pack(side="left")

        # --- Logging ---
        lf_log = ttk.LabelFrame(root, text="Logging")
        lf_log.pack(fill="x", padx=10, pady=6)

        # Log level
        row = ttk.Frame(lf_log); row.pack(fill="x", padx=8, pady=4)
        ttk.Label(row, text="Log Level:", width=16).pack(side="left")
        level_combo = ttk.Combobox(row, textvariable=self.var_log_level, state="readonly",
                                   values=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"], width=12)
        level_combo.pack(side="left")

        # Log to file
        row = ttk.Frame(lf_log); row.pack(fill="x", padx=8, pady=4)
        ttk.Checkbutton(row, text="Log to file", variable=self.var_log_to_file).pack(side="left")

        # Log path + browse (disabled unless log_to_file = True)
        row = ttk.Frame(lf_log); row.pack(fill="x", padx=8, pady=(0, 6))
        ttk.Label(row, text="Log File Path:", width=16).pack(side="left")
        self.ent_log_path = ttk.Entry(row, textvariable=self.var_log_path, width=40)
        self.ent_log_path.pack(side="left", padx=(6, 6))
        self.btn_browse_log = ttk.Button(row, text="Browse", command=self._browse_log_path)
        self.btn_browse_log.pack(side="left")
        self._update_log_path_state()

        # --- Actions (left aligned) ---
        lf_actions = ttk.LabelFrame(root, text="Actions")
        lf_actions.pack(fill="x", padx=10, pady=(6, 10))

        row = ttk.Frame(lf_actions); row.pack(anchor="w", padx=8, pady=6)
        ttk.Button(row, text="Preview File Stats", command=self.preview_stats).pack(side="left")
        ttk.Button(row, text="Scan and Move Files", command=self.move_files).pack(side="left", padx=(8, 0))

    # ---------------- Logging wiring ----------------
    def _on_log_to_file_toggle(self):
        self._update_log_path_state()
        self._apply_logging_config()

    def _update_log_path_state(self):
        state = "normal" if self.var_log_to_file.get() else "disabled"
        self.ent_log_path.configure(state=state)
        self.btn_browse_log.configure(state=state)

    def _browse_log_path(self):
        path = filedialog.asksaveasfilename(
            title="Select Log File",
            defaultextension=".log",
            filetypes=[("Log files", "*.log"), ("All files", "*.*")]
        )
        if path:
            self.var_log_path.set(path)

    def _apply_logging_config(self):
        # Remove old handlers
        for h in list(self.logger.handlers):
            self.logger.removeHandler(h)
        self.logger.setLevel(getattr(logging, self.var_log_level.get(), logging.INFO))

        formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")

        if self.var_log_to_file.get():
            log_path = self.var_log_path.get().strip() or os.path.join(os.getcwd(), "file_mover.log")
            try:
                fh = logging.FileHandler(log_path, encoding="utf-8")
                fh.setFormatter(formatter)
                self.logger.addHandler(fh)
            except Exception as e:
                # Fallback to console if file handler fails
                sh = logging.StreamHandler(sys.stdout)
                sh.setFormatter(formatter)
                self.logger.addHandler(sh)
                if not self.var_silent.get():
                    messagebox.showerror("Logging Error", f"Failed to open log file:\n{e}")
        else:
            sh = logging.StreamHandler(sys.stdout)
            sh.setFormatter(formatter)
            self.logger.addHandler(sh)

        self.logger.debug("Logging configured. level=%s file=%s",
                          self.var_log_level.get(),
                          self.var_log_path.get() if self.var_log_to_file.get() else "STDOUT")

    # ---------------- Helpers ----------------
    def _selected_extensions(self):
        return [ext for ext, var in self.ext_vars.items() if var.get()]

    def select_source(self):
        folder = filedialog.askdirectory(title="Select Source Folder")
        if folder:
            self.src_folder = folder
            self.src_lbl.config(text=folder)
            self.logger.info("Selected source: %s", folder)

    def select_destination(self):
        folder = filedialog.askdirectory(title="Select Destination Folder")
        if folder:
            self.dst_folder = folder
            self.dst_lbl.config(text=folder)
            self.logger.info("Selected destination: %s", folder)

    # ---------------- Actions ----------------
    def preview_stats(self):
        if not self.src_folder:
            if not self.var_silent.get():
                messagebox.showerror("Missing Source", "Please select a source folder.")
            self.logger.warning("Preview failed: missing source folder")
            return

        extensions = self._selected_extensions()
        if not extensions:
            if not self.var_silent.get():
                messagebox.showwarning("No File Types", "Please select at least one file type.")
            self.logger.warning("Preview failed: no file types selected")
            return

        total_files = 0
        for root_dir, _, files in os.walk(self.src_folder):
            for file in files:
                if any(file.lower().endswith(ext) for ext in extensions):
                    total_files += 1

        self.logger.info("Preview: %d matching file(s) found (ext=%s)", total_files, ", ".join(extensions))
        if not self.var_silent.get():
            messagebox.showinfo("Preview", f"Found {total_files} matching file(s). Ready to move.")

    def move_files(self):
        if not self.src_folder or not self.dst_folder:
            if not self.var_silent.get():
                messagebox.showerror("Missing Folder", "Please select both source and destination folders.")
            self.logger.error("Move aborted: missing source or destination")
            return

        extensions = self._selected_extensions()
        if not extensions:
            if not self.var_silent.get():
                messagebox.showwarning("No File Types", "Please select at least one file type.")
            self.logger.error("Move aborted: no file types selected")
            return

        os.makedirs(self.dst_folder, exist_ok=True)
        preserve = self.var_preserve.get()
        delete_after = self.var_delete.get()
        silent = self.var_silent.get()

        self.logger.info(
            "Move started. src=%s dst=%s preserve=%s delete_after=%s ext=%s",
            self.src_folder, self.dst_folder, preserve, delete_after, ", ".join(extensions)
        )

        count = 0
        failed = 0

        for root_dir, _, files in os.walk(self.src_folder):
            for file in files:
                ext = os.path.splitext(file)[1].lower()
                if ext in extensions:
                    src_path = os.path.join(root_dir, file)

                    if preserve:
                        rel_path = os.path.relpath(root_dir, self.src_folder)
                        target_dir = os.path.join(self.dst_folder, rel_path)
                    else:
                        target_dir = os.path.join(self.dst_folder, ext.lstrip("."))

                    os.makedirs(target_dir, exist_ok=True)
                    dst_path = os.path.join(target_dir, file)

                    try:
                        shutil.copy2(src_path, dst_path)
                        count += 1
                        if delete_after:
                            os.remove(src_path)
                    except Exception as e:
                        failed += 1
                        self.logger.exception("Failed to copy %s -> %s: %s", src_path, dst_path, e)

        summary = f"Moved {count} file(s). Failed: {failed}."
        self.logger.info("Move finished. %s", summary)

        if not silent:
            messagebox.showinfo("Done", summary)


if __name__ == "__main__":
    root = tk.Tk()
    app = FileMoverApp(root)
    root.mainloop()
