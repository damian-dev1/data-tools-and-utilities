import json
import csv
import io
import sqlite3
import re
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
from tkinter import font as tkfont
USING_TTKBS = False
try:
    import ttkbootstrap as tb  # type: ignore
    USING_TTKBS = True
except Exception:
    USING_TTKBS = False
def flatten_dict(d, parent_key="", sep="."):
    items = []
    if isinstance(d, dict):
        for k, v in d.items():
            new_key = f"{parent_key}{sep}{k}" if parent_key else k
            items.extend(flatten_dict(v, new_key, sep=sep).items())
    elif isinstance(d, list):
        for idx, v in enumerate(d):
            new_key = f"{parent_key}{sep}{idx}" if parent_key else str(idx)
            items.extend(flatten_dict(v, new_key, sep=sep).items())
    else:
        items.append((parent_key, d))
    return dict(items)
def infer_records(obj):
    if isinstance(obj, list):
        if all(isinstance(x, dict) for x in obj):
            return obj
        return [{"value": x} for x in obj]
    if isinstance(obj, dict):
        for v in obj.values():
            if isinstance(v, list):
                if all(isinstance(x, dict) for x in v):
                    return v
                return [{"value": x} for x in v]
        return [obj]
    return [{"value": obj}]
def json_to_csv_text(json_text, sep="."):
    data = json.loads(json_text)
    records = infer_records(data)
    flat_rows = [flatten_dict(r, sep=sep) for r in records]
    headers = sorted({k for r in flat_rows for k in r.keys()})
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=headers, extrasaction="ignore")
    writer.writeheader()
    for r in flat_rows:
        row = {k: r.get(k, "") for k in headers}
        writer.writerow(row)
    return out.getvalue()
_SQL_IDENT_RE = re.compile(r"[^A-Za-z0-9_]")
def _sql_ident(name: str) -> str:
    safe = _SQL_IDENT_RE.sub("_", name.strip() or "col")
    return f"\"{safe}\""
def _infer_sql_type(values):
    """
    Infer a SQLite column type (INTEGER, REAL, TEXT) from a sequence of values.
    Booleans become INTEGER (0/1). None is ignored.
    """
    saw_real = False
    saw_int = False
    for v in values:
        if v is None:
            continue
        if isinstance(v, bool):
            saw_int = True
            continue
        if isinstance(v, int):
            saw_int = True
            continue
        if isinstance(v, float):
            saw_real = True
            continue
        return "TEXT"
    if saw_real and not saw_int:
        return "REAL"
    if saw_real and saw_int:
        return "REAL"
    if saw_int:
        return "INTEGER"
    return "TEXT"
def json_to_sqlite(json_text, db_path: str, table_name: str, sep="."):
    data = json.loads(json_text)
    records = infer_records(data)
    flat_rows = [flatten_dict(r, sep=sep) for r in records]
    if not flat_rows:
        raise ValueError("No rows to write.")
    headers = sorted({k for r in flat_rows for k in r.keys()})
    col_values = {h: [] for h in headers}
    for r in flat_rows:
        for h in headers:
            v = r.get(h, None)
            if v == "":
                v = None
            col_values[h].append(v)
    col_types = {h: _infer_sql_type(col_values[h]) for h in headers}
    quoted_cols = [_sql_ident(h) for h in headers]
    col_defs = [f"{quoted_cols[i]} {col_types[headers[i]]}" for i in range(len(headers))]
    placeholders = ", ".join(["?"] * len(headers))
    insert_sql = f"INSERT INTO {_sql_ident(table_name)} ({', '.join(quoted_cols)}) VALUES ({placeholders})"
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?;", (table_name,))
        exists = cur.fetchone() is not None
        if exists:
            replace = messagebox.askyesno(
                "Table Exists",
                f"Table '{table_name}' already exists in:\n{db_path}\n\nReplace it? (Yes = DROP & CREATE, No = append)"
            )
            if replace:
                cur.execute(f"DROP TABLE {_sql_ident(table_name)}")
        if (not exists) or replace:
            cur.execute(f"CREATE TABLE {_sql_ident(table_name)} ({', '.join(col_defs)})")
        rows = []
        for r in flat_rows:
            row = []
            for h in headers:
                v = r.get(h, None)
                if v == "":
                    v = None
                if isinstance(v, bool):
                    v = 1 if v else 0
                row.append(v)
            rows.append(tuple(row))
        cur.executemany(insert_sql, rows)
        conn.commit()
    finally:
        conn.close()
class JsonToCsvApp(ttk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.master: tk.Tk = master
        self.sep_var = tk.StringVar(value=".")
        self.autoconvert_var = tk.BooleanVar(value=False)
        self._last_open_dir = ""
        self._last_save_dir = ""
        self._init_fonts_and_styles()
        self._build_ui()
        self._bind_keys()
    def _init_fonts_and_styles(self):
        try:
            self.font_mono = tkfont.Font(family="Consolas", size=10)
            base = tkfont.nametofont("TkDefaultFont")
            base.configure(size=10)
        except Exception:
            self.font_mono = tkfont.Font(size=10)
        self.style = ttk.Style(self.master)
        self.style.configure("AppTitle.TLabel", font=("TkDefaultFont", 14, "bold"))
        self.style.configure("Section.TLabel", font=("TkDefaultFont", 10, "bold"))
        self.style.configure("Status.TLabel", font=("TkDefaultFont", 10))
    def _build_ui(self):
        self.master.title("JSON → CSV/SQLite Converter")
        self.master.geometry("1180x720")
        self.master.minsize(940, 560)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        header = ttk.Frame(self, padding=(10, 10, 10, 8))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(10, weight=1)
        ttk.Label(header, text="JSON → CSV / SQLite", style="AppTitle.TLabel").grid(
            row=0, column=0, padx=(0, 12), sticky="w"
        )
        ttk.Label(header, text="Flatten sep:").grid(row=0, column=1, sticky="e", padx=(0, 4))
        sep_entry = ttk.Entry(header, width=4, textvariable=self.sep_var, justify="center")
        sep_entry.grid(row=0, column=2, sticky="w")
        ttk.Checkbutton(header, text="Auto-convert on paste", variable=self.autoconvert_var).grid(
            row=0, column=3, padx=12
        )
        ttk.Button(header, text="Import JSON", command=self.on_import_json).grid(row=0, column=4, padx=6, sticky="e")
        ttk.Button(header, text="Paste JSON", command=self.on_paste_json).grid(row=0, column=5, padx=6, sticky="e")
        ttk.Button(header, text="Convert ▶", command=self.on_convert).grid(row=0, column=6, padx=6, sticky="e")
        ttk.Button(header, text="Copy CSV", command=self.on_copy_csv).grid(row=0, column=7, padx=6, sticky="e")
        ttk.Button(header, text="Export CSV", command=self.on_export_csv).grid(row=0, column=8, padx=6, sticky="e")
        ttk.Button(header, text="Export SQLite", command=self.on_export_sqlite).grid(row=0, column=9, padx=6, sticky="e")
        ttk.Button(header, text="Clear", command=self.on_clear).grid(row=0, column=10, padx=(6, 0), sticky="e")
        main = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        main.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        left_frame = ttk.Frame(main, padding=6)
        right_frame = ttk.Frame(main, padding=6)
        for f in (left_frame, right_frame):
            f.columnconfigure(0, weight=1)
            f.rowconfigure(1, weight=1)
        ttk.Label(left_frame, text="JSON Input", style="Section.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 6)
        )
        lcontainer = ttk.Frame(left_frame)
        lcontainer.grid(row=1, column=0, sticky="nsew")
        lcontainer.columnconfigure(0, weight=1)
        lcontainer.rowconfigure(0, weight=1)
        self.json_text = tk.Text(lcontainer, wrap="none", undo=True, font=self.font_mono)
        l_y = ttk.Scrollbar(lcontainer, orient="vertical", command=self.json_text.yview)
        l_x = ttk.Scrollbar(lcontainer, orient="horizontal", command=self.json_text.xview)
        self.json_text.configure(yscrollcommand=l_y.set, xscrollcommand=l_x.set)
        self.json_text.grid(row=0, column=0, sticky="nsew")
        l_y.grid(row=0, column=1, sticky="ns")
        l_x.grid(row=1, column=0, sticky="ew")
        ttk.Label(right_frame, text="CSV Output", style="Section.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 6)
        )
        rcontainer = ttk.Frame(right_frame)
        rcontainer.grid(row=1, column=0, sticky="nsew")
        rcontainer.columnconfigure(0, weight=1)
        rcontainer.rowconfigure(0, weight=1)
        self.csv_text = tk.Text(rcontainer, wrap="none", undo=False, font=self.font_mono, state="normal")
        r_y = ttk.Scrollbar(rcontainer, orient="vertical", command=self.csv_text.yview)
        r_x = ttk.Scrollbar(rcontainer, orient="horizontal", command=self.csv_text.xview)
        self.csv_text.configure(yscrollcommand=r_y.set, xscrollcommand=r_x.set)
        self.csv_text.grid(row=0, column=0, sticky="nsew")
        r_y.grid(row=0, column=1, sticky="ns")
        r_x.grid(row=1, column=0, sticky="ew")
        main.add(left_frame, weight=1)
        main.add(right_frame, weight=1)
        self.status = ttk.Label(self, text="Ready", anchor="w", style="Status.TLabel")
        self.status.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 10))
        self.pack(fill="both", expand=True)
    def _bind_keys(self):
        self.master.bind("<Control-Return>", lambda e: self.on_convert())
        self.master.bind("<Control-Shift-c>", lambda e: self.on_copy_csv())
        self.master.bind("<Control-Shift-v>", lambda e: self.on_paste_json())
        self.master.bind("<Control-o>", lambda e: self.on_import_json())
        self.master.bind("<Control-s>", lambda e: self.on_export_csv())
        self.master.bind("<Control-e>", lambda e: self.on_export_sqlite())  # Export SQLite
        self.json_text.bind("<<Paste>>", self._on_text_paste)
        self.json_text.bind("<Button-2>", lambda e: self.master.after(50, self._auto_convert_if_enabled()))
        self.json_text.bind("<Button-3>", lambda e: None)
    def _on_text_paste(self, event):
        self.master.after(50, self._auto_convert_if_enabled())
        return None
    def _auto_convert_if_enabled(self):
        if self.autoconvert_var.get():
            self.on_convert()
    def on_import_json(self):
        path = filedialog.askopenfilename(
            title="Import JSON",
            initialdir=self._last_open_dir or "",
            filetypes=[("JSON files", "*.json;*.ndjson;*.geojson"), ("All files", "*.*")]
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
        except Exception as e:
            messagebox.showerror("Open Error", f"Failed to open file:\n{e}")
            return
        self._last_open_dir = str(path.rsplit("/", 1)[0] if "/" in path else path.rsplit("\\", 1)[0] if "\\" in path else "")
        self.json_text.delete("1.0", "end")
        self.json_text.insert("1.0", text)
        self._set_status(f"Loaded JSON: {path}")
        self._auto_convert_if_enabled()
    def on_export_csv(self):
        csv_text = self.csv_text.get("1.0", "end").strip()
        if not csv_text:
            left = self.json_text.get("1.0", "end").strip()
            if not left:
                self._set_status("Nothing to export.")
                return
            try:
                csv_text = json_to_csv_text(left, sep=self.sep_var.get() or ".")
                self.csv_text.config(state="normal")
                self.csv_text.delete("1.0", "end")
                self.csv_text.insert("1.0", csv_text)
            except Exception as e:
                messagebox.showerror("Export Error", f"Cannot export, conversion failed:\n{e}")
                return
        path = filedialog.asksaveasfilename(
            title="Export CSV",
            initialdir=self._last_save_dir or "",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(csv_text)
        except Exception as e:
            messagebox.showerror("Save Error", f"Failed to save CSV:\n{e}")
            return
        self._last_save_dir = str(path.rsplit("/", 1)[0] if "/" in path else path.rsplit("\\", 1)[0] if "\\" in path else "")
        self._set_status(f"Exported CSV: {path}")
    def on_export_sqlite(self):
        text = self.json_text.get("1.0", "end").strip()
        if not text:
            self._set_status("No JSON to export.")
            return
        db_path = filedialog.asksaveasfilename(
            title="Export to SQLite",
            defaultextension=".db",
            filetypes=[("SQLite DB", "*.db"), ("All files", "*.*")]
        )
        if not db_path:
            return
        table = simpledialog.askstring("Table Name", "Enter table name:", initialvalue="data", parent=self.master)
        if not table:
            self._set_status("Export cancelled (no table name).")
            return
        try:
            json_to_sqlite(text, db_path=db_path, table_name=table, sep=self.sep_var.get() or ".")
        except Exception as e:
            messagebox.showerror("SQLite Export Error", str(e))
            return
        self._set_status(f"Exported to SQLite: {db_path} (table '{table}')")
    def on_paste_json(self):
        try:
            clip = self.master.clipboard_get()
        except tk.TclError:
            self._set_status("Clipboard empty.")
            return
        self.json_text.delete("1.0", "end")
        self.json_text.insert("1.0", clip)
        self._set_status("Pasted JSON from clipboard.")
        self._auto_convert_if_enabled()
    def on_convert(self):
        text = self.json_text.get("1.0", "end").strip()
        if not text:
            self._set_status("No JSON to convert.")
            return
        try:
            csv_out = json_to_csv_text(text, sep=self.sep_var.get() or ".")
        except Exception as e:
            messagebox.showerror("Conversion Error", str(e))
            self._set_status("Conversion failed.")
            return
        self.csv_text.config(state="normal")
        self.csv_text.delete("1.0", "end")
        self.csv_text.insert("1.0", csv_out)
        self.csv_text.config(state="normal")
        self._set_status("Converted JSON to CSV.")
    def on_copy_csv(self):
        data = self.csv_text.get("1.0", "end").strip()
        if not data:
            self._set_status("No CSV to copy.")
            return
        self.master.clipboard_clear()
        self.master.clipboard_append(data)
        self._set_status("CSV copied to clipboard.")
    def on_clear(self):
        self.json_text.delete("1.0", "end")
        self.csv_text.delete("1.0", "end")
        self._set_status("Cleared.")
    def _set_status(self, msg):
        self.status.config(text=msg)
def main():
    if USING_TTKBS:
        style = tb.Style(theme="darkly")
        root = style.master
    else:
        root = tk.Tk()
    app = JsonToCsvApp(root)
    app.mainloop()
if __name__ == "__main__":
    main()
