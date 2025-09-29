import os
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
import pandas as pd
import ttkbootstrap as tb
from ttkbootstrap.constants import *

DEFAULT_SOURCE_CODES = ["pos_337", "src_virtualstock"]

class M2StockApp(tb.Window):
    def __init__(self):
        super().__init__(themename="darkly")
        self.title("M2 Stock Import CSV Generator")
        self.geometry("1200x700")

        self.m2_df: pd.DataFrame | None = None
        self.original_file_path: str | None = None
        self.source_codes: list[str] = DEFAULT_SOURCE_CODES.copy()
        self.output_folder = os.path.expanduser("~/Downloads")
        self.chunk_size = 1000

        self.use_raw_sku = tk.BooleanVar(value=False)
        self.available_columns: list[str] = []
        self.sku_column = tk.StringVar(value="")
        self.qty_column = tk.StringVar(value="")

        self.build_ui()

    def build_ui(self):
        # ----- Shell layout
        root_pane = tb.Panedwindow(self, orient="horizontal")
        root_pane.pack(fill=BOTH, expand=True)

        # Left: sidebar (stats)
        sidebar = tb.Frame(root_pane, padding=(12, 12))
        self.stats_label = tb.Label(
            sidebar,
            text="Stats:\n\nNo file loaded",
            justify=LEFT,
            anchor=NW
        )
        self.stats_label.pack(anchor=NW)
        root_pane.add(sidebar, weight=0)

        # Right: notebook
        right = tb.Frame(root_pane)
        root_pane.add(right, weight=1)

        notebook = tb.Notebook(right)
        notebook.pack(fill=BOTH, expand=True)

        # ----- Configuration tab
        tab = tb.Frame(notebook, padding=12)
        notebook.add(tab, text="Configuration")

        # grid config for clean layout
        for c in range(0, 3):
            tab.columnconfigure(c, weight=1 if c == 1 else 0)
        tab.columnconfigure(3, weight=0)  # buttons
        tab.rowconfigure(99, weight=1)

        # Row 0: file select
        tb.Label(tab, text="Select CSV File:").grid(row=0, column=0, sticky=W, pady=(0, 6))
        self.entry_file_path = tb.Entry(tab)
        self.entry_file_path.grid(row=0, column=1, sticky=EW, padx=(0, 8), pady=(0, 6))
        tb.Button(tab, text="Browse", command=self.select_file).grid(row=0, column=2, sticky=E, pady=(0, 6))
        self.load_button = tb.Button(tab, text="Load", command=self.load_data, state=DISABLED)
        self.load_button.grid(row=0, column=3, sticky=E, pady=(0, 6))

        # Row 1: SKU column
        tb.Label(tab, text="SKU Column:").grid(row=1, column=0, sticky=W, pady=6)
        self.dropdown_sku = tb.Combobox(tab, textvariable=self.sku_column, state="readonly")
        self.dropdown_sku.grid(row=1, column=1, sticky=EW, padx=(0, 8), pady=6)
        self.dropdown_sku.bind("<<ComboboxSelected>>", self.check_column_selection)

        # Row 2: Qty column
        tb.Label(tab, text="Qty Column:").grid(row=2, column=0, sticky=W, pady=6)
        self.dropdown_qty = tb.Combobox(tab, textvariable=self.qty_column, state="readonly")
        self.dropdown_qty.grid(row=2, column=1, sticky=EW, padx=(0, 8), pady=6)
        self.dropdown_qty.bind("<<ComboboxSelected>>", self.check_column_selection)

        # Row 3: raw key
        tb.Checkbutton(tab, text="Use 'key' as SKU (no split)", variable=self.use_raw_sku)\
            .grid(row=3, column=1, sticky=W, pady=6)

        # Right block: Source codes
        source_frame = tb.LabelFrame(tab, text="Source Codes", padding=10)
        source_frame.grid(row=1, column=2, rowspan=3, columnspan=2, sticky=NW, padx=(12, 0))

        self.listbox_sources = tk.Listbox(
            source_frame, height=6, bg="#2b2b2b", fg="white", selectbackground="#444"
        )
        self.listbox_sources.pack(fill=X)
        btn_frame = tb.Frame(source_frame)
        btn_frame.pack(pady=6)
        tb.Button(btn_frame, text="Add", command=self.add_source_code).grid(row=0, column=0, padx=4)
        tb.Button(btn_frame, text="Remove", command=self.remove_source_code).grid(row=0, column=1, padx=4)
        tb.Button(btn_frame, text="Reset", command=self.reset_source_codes).grid(row=0, column=2, padx=4)
        self.refresh_source_list()

        # Row 10: Output folder
        tb.Label(tab, text="Output Folder:").grid(row=10, column=0, sticky=W, pady=(18, 6))
        self.entry_output_folder = tb.Entry(tab)
        self.entry_output_folder.insert(0, self.output_folder)
        self.entry_output_folder.grid(row=10, column=1, sticky=EW, padx=(0, 8), pady=(18, 6))
        tb.Button(tab, text="Choose", command=self.choose_output_folder).grid(row=10, column=2, sticky=W, pady=(18, 6))

        # Row 11: Chunk size
        tb.Label(tab, text="Chunk Size:").grid(row=11, column=0, sticky=W, pady=6)
        self.entry_chunk_size = tb.Entry(tab, width=12)
        self.entry_chunk_size.insert(0, str(self.chunk_size))
        self.entry_chunk_size.grid(row=11, column=1, sticky=W, pady=6)

        # Row 12: Export
        tb.Button(tab, text="Export M2 CSV", bootstyle=SUCCESS, command=self.export_csv)\
            .grid(row=12, column=1, sticky=W, pady=(12, 0))

        # ----- Preview tab
        tprev = tb.Frame(notebook, padding=12)
        notebook.add(tprev, text="Preview")

        # Tree + scrollbar
        self.tree = tb.Treeview(tprev, show="headings")
        vs = tb.Scrollbar(tprev, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vs.set)
        self.tree.pack(side=LEFT, fill=BOTH, expand=True)
        vs.pack(side=RIGHT, fill=Y)

    # --- Source code ops
    def refresh_source_list(self):
        self.listbox_sources.delete(0, "end")
        for code in self.source_codes:
            self.listbox_sources.insert("end", code)

    def add_source_code(self):
        new_code = simpledialog.askstring("Add Source Code", "Enter new source_code:")
        if new_code:
            self.source_codes.append(new_code.strip())
            self.refresh_source_list()

    def remove_source_code(self):
        sel = self.listbox_sources.curselection()
        if sel:
            del self.source_codes[sel[0]]
            self.refresh_source_list()

    def reset_source_codes(self):
        self.source_codes = DEFAULT_SOURCE_CODES.copy()
        self.refresh_source_list()

    # --- File/folder
    def choose_output_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.output_folder = folder
            self.entry_output_folder.delete(0, "end")
            self.entry_output_folder.insert(0, folder)

    def select_file(self):
        file_path = filedialog.askopenfilename(filetypes=[("CSV files", "*.csv")])
        if not file_path:
            return
        self.entry_file_path.delete(0, "end")
        self.entry_file_path.insert(0, file_path)
        self.original_file_path = file_path
        self.load_columns(file_path)

    # --- Data / columns
    def load_columns(self, file_path: str):
        try:
            df = pd.read_csv(file_path, nrows=1)
            self.available_columns = list(df.columns)

            self.dropdown_sku["values"] = self.available_columns
            self.dropdown_qty["values"] = self.available_columns

            if "key" in self.available_columns:
                self.sku_column.set("key")
            elif "sku" in self.available_columns:
                self.sku_column.set("sku")

            for guess in ("free_stock_tgt", "qty", "quantity", "stock_qty"):
                if guess in self.available_columns:
                    self.qty_column.set(guess)
                    break

            self.check_column_selection()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load columns: {e}")

    def check_column_selection(self, *_):
        ready = bool((self.entry_file_path.get() or "").strip() and
                     (self.sku_column.get() or "").strip() and
                     (self.qty_column.get() or "").strip())
        self.load_button.configure(state=NORMAL if ready else DISABLED)

    def load_data(self):
        fp = (self.entry_file_path.get() or "").strip()
        if not fp:
            messagebox.showwarning("Missing", "Select a CSV file.")
            return
        try:
            self.process_csv(fp)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load data: {e}")

    # --- Transform / preview
    def process_csv(self, file_path: str):
        df = pd.read_csv(file_path)

        sku_col = (self.sku_column.get() or "").strip()
        qty_col = (self.qty_column.get() or "").strip()
        if not sku_col or not qty_col:
            return

        if self.use_raw_sku.get():
            df["sku"] = df[sku_col]
        else:
            def split_sku(x):
                if isinstance(x, str):
                    return x.split("|")[0].strip()
                return x
            df["sku"] = df[sku_col].apply(split_sku)

        # qty -> whole number (>=0), robust coercion
        qty_series = pd.to_numeric(df[qty_col], errors="coerce").fillna(0)
        qty_series = qty_series.round(0).astype(int)
        qty_series = qty_series.clip(lower=0)

        rows = []
        for sku, qty_val in zip(df["sku"], qty_series):
            stock_status = 1 if qty_val > 0 else 0
            for source in self.source_codes:
                rows.append(
                    {
                        "sku": sku,
                        "stock_status": stock_status,
                        "source_code": source,
                        "qty": int(qty_val),
                    }
                )

        self.m2_df = pd.DataFrame(rows, columns=["sku", "stock_status", "source_code", "qty"])
        self.preview_data(self.m2_df.head(200))
        self.update_stats()

    def preview_data(self, df: pd.DataFrame):
        # clear
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        self.tree["columns"] = list(df.columns)
        for col in df.columns:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=160, anchor=W)
        for _, row in df.iterrows():
            self.tree.insert("", "end", values=list(row.values))

    def update_stats(self):
        if self.m2_df is None:
            return
        total = int(self.m2_df["sku"].nunique())
        in_stock = int(self.m2_df[self.m2_df["stock_status"] == 1]["sku"].nunique())
        out_stock = int(self.m2_df[self.m2_df["stock_status"] == 0]["sku"].nunique())
        sources = len(self.source_codes)
        self.stats_label.config(
            text=f"Stats:\n\nTotal SKUs: {total}\nIn Stock: {in_stock}\nOut of Stock: {out_stock}\nSource Codes: {sources}"
        )

    # --- Export
    def export_csv(self):
        if self.m2_df is None or self.original_file_path is None:
            messagebox.showwarning("Warning", "No data to export")
            return
        try:
            chunk_size = max(1, int(self.entry_chunk_size.get() or "1000"))
            base_name = os.path.splitext(os.path.basename(self.original_file_path))[0]
            os.makedirs(self.output_folder, exist_ok=True)

            parts = 0
            for i in range(0, len(self.m2_df), chunk_size):
                chunk = self.m2_df.iloc[i: i + chunk_size]
                parts += 1
                output_name = f"{base_name}_m2_import_part{parts}.csv"
                output_path = os.path.join(self.output_folder, output_name)
                chunk.to_csv(output_path, index=False)

            messagebox.showinfo("Success", f"Exported {parts} file(s) to:\n{self.output_folder}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to export CSV: {e}")

if __name__ == "__main__":
    app = M2StockApp()
    app.mainloop()
