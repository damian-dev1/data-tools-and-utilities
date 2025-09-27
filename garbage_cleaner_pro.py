import os
import sys
import shutil
import stat
import time
import json
import logging
import threading
import queue
import tempfile
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Dict, Tuple, Literal

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox
    from tkinter import ttk as _ttk
except Exception:
    raise SystemExit("Tkinter is required to run this application.")

try:
    from ttkbootstrap import Style
    from ttkbootstrap import ttk
    _HAS_TTKB = True
except Exception:
    from tkinter import ttk  # type: ignore
    Style = None             # type: ignore
    _HAS_TTKB = False

try:
    import psutil  # type: ignore
except Exception:
    psutil = None  # type: ignore

try:
    from send2trash import send2trash  # type: ignore
except Exception:
    send2trash = None  # type: ignore

from logging.handlers import RotatingFileHandler

APP_NAME = "Garbage Cleaner Pro"
APP_VERSION = "0.4.0"
APP_ROOT = Path.cwd()
LOGS_DIR = APP_ROOT / "logs"
LOGS_DIR.mkdir(exist_ok=True)
DEFAULT_LOG = LOGS_DIR / "garbage_cleaner.log"
QUARANTINE_DIR = Path.home() / ".garbage_cleaner_quarantine"
DEFAULT_RULES_FILE = APP_ROOT / "clean_rules.json"
DEFAULT_SCHEDULE_FILE = APP_ROOT / "schedules.json"

# ---------------------- Utility ----------------------

def human_bytes(n: int) -> str:
    step = 1024.0
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < step:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= step
    return f"{n:.1f} PB"


def ensure_quarantine() -> Path:
    QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)
    return QUARANTINE_DIR


def is_windows() -> bool:
    return sys.platform.startswith("win")

def is_macos() -> bool:
    return sys.platform == "darwin"


def is_linux() -> bool:
    return sys.platform.startswith("linux")


# ---------------------- Tooltips ----------------------
class Tooltip:
    def __init__(self, widget: tk.Widget, text: str, *, delay: int = 500):
        self.widget = widget
        self.text = text
        self.delay = delay
        self._after_id: Optional[str] = None
        self._tip: Optional[tk.Toplevel] = None
        widget.bind("<Enter>", self._schedule)
        widget.bind("<Leave>", self._hide)
        widget.bind("<ButtonPress>", self._hide)

    def _schedule(self, _=None):
        self._cancel()
        self._after_id = self.widget.after(self.delay, self._show)

    def _cancel(self):
        if self._after_id:
            try:
                self.widget.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _show(self):
        if self._tip or not self.text:
            return
        x = self.widget.winfo_rootx() + 10
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        tip = tk.Toplevel(self.widget)
        tip.wm_overrideredirect(True)
        tip.wm_geometry(f"+{x}+{y}")
        bg = "#111827"; fg = "#e5e7eb"; bd = "#374151"
        frm = tk.Frame(tip, bg=bg, bd=1, relief="solid", highlightthickness=0)
        frm.pack()
        lbl = tk.Label(frm, text=self.text, bg=bg, fg=fg, padx=8, pady=4, justify="left")
        lbl.pack()
        self._tip = tip

    def _hide(self, _=None):
        self._cancel()
        if self._tip:
            try:
                self._tip.destroy()
            except Exception:
                pass
            self._tip = None


# ---------------------- Shutdown Mixin ----------------------
class ShutdownMixin:
    def _setup_shutdown(self, root, *, log_path=DEFAULT_LOG):
        self.root = root
        self._is_shutting_down = False
        self._after_handles: List[int] = []
        self._threads_to_join: List[threading.Thread] = []
        self._queues_to_drain: List[queue.Queue] = []
        self._on_shutdown_callbacks: List[Callable] = []
        self._setup_logging(log_path)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _setup_logging(self, log_path: Path):
        logger = logging.getLogger(APP_NAME)
        logger.setLevel(logging.INFO)
        handler = RotatingFileHandler(log_path, maxBytes=2_000_000, backupCount=5, encoding="utf-8")
        formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
        handler.setFormatter(formatter)
        logger.handlers.clear()
        logger.addHandler(handler)
        self.log = logger.info
        self.err = logging.getLogger(APP_NAME).exception

    def register_after(self, handle_id: int):
        self._after_handles.append(handle_id)

    def register_thread(self, t: threading.Thread):
        self._threads_to_join.append(t)

    def register_queue(self, q: queue.Queue):
        self._queues_to_drain.append(q)

    def on_shutdown(self, fn: Callable):
        self._on_shutdown_callbacks.append(fn)
        return fn

    def on_close(self):
        if getattr(self, "_is_shutting_down", False):
            return
        self._is_shutting_down = True
        try:
            self.log("Application is closing…")
            for h in self._after_handles:
                try:
                    self.root.after_cancel(h)
                except Exception:
                    pass
            self._after_handles.clear()
            for q in self._queues_to_drain:
                try:
                    while True:
                        q.get_nowait(); q.task_done()
                except Exception:
                    pass
                try:
                    q.join()
                except Exception:
                    pass
            self._queues_to_drain.clear()
            for fn in self._on_shutdown_callbacks:
                try:
                    fn()
                except Exception:
                    pass
            for t in self._threads_to_join:
                if t is threading.current_thread():
                    continue
                try:
                    t.join(timeout=1.0)
                except Exception:
                    pass
            self._threads_to_join.clear()
            try:
                self.root.destroy()
            except Exception:
                pass
            try:
                logging.shutdown()
            except Exception:
                pass
        except Exception:
            try:
                self.root.destroy()
            except Exception:
                pass
            try:
                logging.shutdown()
            except Exception:
                pass


# ---------------------- Rules & Config ----------------------
ActionType = Literal["quarantine", "delete", "recycle"]

@dataclass
class PathRule:
    name: str
    path: str
    patterns: List[str] = field(default_factory=lambda: ["*"])
    min_age_days: int = 0
    remove_empty_dirs: bool = True
    action: ActionType = "quarantine"
    enabled: bool = True

    def resolve_base(self) -> Path:
        return Path(os.path.expandvars(os.path.expanduser(self.path))).resolve()


@dataclass
class AppConfig:
    dry_run: bool = True
    quarantine_enabled: bool = True
    follow_symlinks: bool = False
    max_delete_per_rule: int = 50_000
    max_total_delete: int = 200_000
    log_age_off_days: int = 30
    hard_recycle_only: bool = False


@dataclass
class ScanResult:
    rule: PathRule
    files: List[Path] = field(default_factory=list)
    total_size: int = 0


# ---------------------- Built-in Rule Helpers ----------------------

def browser_cache_rules() -> List[PathRule]:
    rules: List[PathRule] = []
    home = Path.home()
    if is_windows():
        chrome_base = home / "AppData/Local/Google/Chrome/User Data"
        if chrome_base.exists():
            for prof in chrome_base.glob("*"):
                if (prof / "Cache").exists():
                    rules.append(PathRule(name=f"Chrome {prof.name} Cache", path=str(prof / "Cache"), patterns=["**/*"], min_age_days=2))
        edge_base = home / "AppData/Local/Microsoft/Edge/User Data"
        if edge_base.exists():
            for prof in edge_base.glob("*"):
                if (prof / "Cache").exists():
                    rules.append(PathRule(name=f"Edge {prof.name} Cache", path=str(prof / "Cache"), patterns=["**/*"], min_age_days=2))
        fx_base = home / "AppData/Roaming/Mozilla/Firefox/Profiles"
        if fx_base.exists():
            for prof in fx_base.glob("*.default*"):
                cache = home / "AppData/Local/Mozilla/Firefox/Profiles" / prof.name / "cache2"
                if cache.exists():
                    rules.append(PathRule(name=f"Firefox {prof.name} Cache", path=str(cache), patterns=["**/*"], min_age_days=2))
    elif is_macos():
        for base in [home/"Library/Caches/Google/Chrome", home/"Library/Caches/Firefox", home/"Library/Caches/Microsoft Edge"]:
            if base.exists():
                rules.append(PathRule(name=f"Browser Cache ({base.name})", path=str(base), patterns=["**/*"], min_age_days=2))
    else:  # Linux
        for base in [home/".cache/google-chrome", home/".cache/chromium", home/".cache/mozilla/firefox"]:
            if base.exists():
                rules.append(PathRule(name=f"Browser Cache ({base.name})", path=str(base), patterns=["**/*"], min_age_days=2))
    return rules


def os_specific_rules() -> List[PathRule]:
    rules: List[PathRule] = []
    home = Path.home()
    if is_windows():
        rules.extend([
            PathRule(name="Windows Temp", path=str(home/"AppData/Local/Temp"), patterns=["**/*"], min_age_days=1),
            PathRule(name="Windows Prefetch", path=str(Path(os.environ.get("SystemRoot", "C:/Windows"))/"Prefetch"), patterns=["*.pf"], min_age_days=7),
            PathRule(name="Windows ErrorReports", path=str(home/"AppData/Local/Microsoft/Windows/WER/ReportArchive"), patterns=["**/*"], min_age_days=7),
            PathRule(name="Edge GPUCache", path=str(home/"AppData/Local/Microsoft/Edge/User Data/Default/GPUCache"), patterns=["**/*"], min_age_days=2),
        ])
    elif is_macos():
        rules.extend([
            PathRule(name="macOS User Cache", path=str(home/"Library/Caches"), patterns=["**/*"], min_age_days=3),
            PathRule(name="macOS Logs", path=str(home/"Library/Logs"), patterns=["**/*.log"], min_age_days=7),
        ])
    else:  # Linux
        rules.extend([
            PathRule(name="Linux ~/.cache", path=str(home/".cache"), patterns=["**/*"], min_age_days=3),
            PathRule(name="Linux Thumbnail Cache", path=str(home/".cache/thumbnails"), patterns=["**/*"], min_age_days=7),
        ])
    return rules


def default_rules() -> List[PathRule]:
    rules = [
        PathRule(name="System TEMP", path=tempfile.gettempdir(), patterns=["*"], min_age_days=1),
        PathRule(name="Python __pycache__", path=str(Path.home()), patterns=["**/__pycache__/*"], min_age_days=0),
    ]
    rules.extend(browser_cache_rules())
    rules.extend(os_specific_rules())
    return rules


# ---------------------- Cleaner Engine ----------------------
class CleanerEngine:
    def __init__(self, cfg: AppConfig):
        self.cfg = cfg
        self.total_deleted = 0
        self._stop = threading.Event()
        self._pause = threading.Event()
        self._pause.clear()

    def stop(self):
        self._stop.set()
        self._pause.clear()

    def toggle_pause(self, value: bool):
        if value:
            self._pause.set()
        else:
            self._pause.clear()

    def wait_if_paused(self):
        while self._pause.is_set() and not self._stop.is_set():
            time.sleep(0.1)

    def older_than(self, p: Path, cutoff: float) -> bool:
        try:
            st = p.stat()
            return st.st_mtime < cutoff
        except (FileNotFoundError, PermissionError):
            return False

    def enumerate_rule(self, rule: PathRule) -> ScanResult:
        res = ScanResult(rule=rule)
        if not rule.enabled:
            return res
        base = rule.resolve_base()
        if not base.exists():
            return res
        cutoff = time.time() - rule.min_age_days * 86400
        seen: set[Path] = set()
        for pattern in rule.patterns:
            try:
                for p in base.rglob(pattern):
                    if self._stop.is_set():
                        return res
                    self.wait_if_paused()
                    try:
                        if p in seen or p.is_dir():
                            continue
                        if not self.cfg.follow_symlinks and p.is_symlink():
                            continue
                        if rule.min_age_days > 0 and not self.older_than(p, cutoff):
                            continue
                        seen.add(p)
                        res.files.append(p)
                        try:
                            res.total_size += p.stat().st_size
                        except Exception:
                            pass
                        if len(res.files) >= self.cfg.max_delete_per_rule:
                            break
                    except (PermissionError, FileNotFoundError):
                        continue
            except Exception:
                continue
        return res

    def _resolve_action(self, rule: PathRule) -> ActionType:
        if self.cfg.hard_recycle_only:
            return "recycle"
        return rule.action

    def _recycle_or_quarantine_or_delete(self, p: Path, rule: PathRule, log: Callable[[str], None]) -> bool:
        try:
            if self.cfg.dry_run:
                return True
            action = self._resolve_action(rule)
            if action == "recycle" and send2trash is not None:
                send2trash(str(p))
                return True
            if action == "delete" or not self.cfg.quarantine_enabled:
                try:
                    p.chmod(p.stat().st_mode | stat.S_IWRITE)
                except Exception:
                    pass
                p.unlink(missing_ok=True)
                return True
            qroot = ensure_quarantine() / rule.name
            qroot.mkdir(parents=True, exist_ok=True)
            try:
                rel = p.relative_to(rule.resolve_base())
            except Exception:
                rel = Path(p.name)
            dest = (qroot / rel).with_suffix(p.suffix)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(p), str(dest))
            return True
        except Exception as e:
            log(f"Failed: {p} → {e}")
            return False

    def act_on_files(self, res: ScanResult, log: Callable[[str], None]) -> Tuple[int, int]:
        deleted_files = 0
        freed_bytes = 0
        for p in list(res.files):
            if self._stop.is_set():
                break
            self.wait_if_paused()
            if deleted_files >= self.cfg.max_total_delete:
                break
            size = 0
            try:
                size = p.stat().st_size
            except Exception:
                size = 0
            ok = self._recycle_or_quarantine_or_delete(p, res.rule, log)
            if ok:
                freed_bytes += size
                deleted_files += 1
        return deleted_files, freed_bytes

    def cleanup_empty_dirs(self, base: Path):
        if self.cfg.dry_run:
            return
        for root, dirs, files in os.walk(base, topdown=False):
            if self._stop.is_set():
                return
            self.wait_if_paused()
            p = Path(root)
            try:
                if not any(Path(root).iterdir()):
                    p.rmdir()
            except Exception:
                pass


# ---------------------- Persistence ----------------------
class ConfigStore:
    def __init__(self, rules_file: Path = DEFAULT_RULES_FILE, schedule_file: Path = DEFAULT_SCHEDULE_FILE):
        self.rules_file = rules_file
        self.schedule_file = schedule_file

    def load(self) -> Tuple[AppConfig, List[PathRule]]:
        if not self.rules_file.exists():
            return AppConfig(), list(default_rules())
        data = json.loads(self.rules_file.read_text(encoding="utf-8"))
        cfg = AppConfig(**data.get("config", {}))
        rules = [PathRule(**r) for r in data.get("rules", [])]
        return cfg, rules

    def save(self, cfg: AppConfig, rules: List[PathRule]):
        payload = {"config": asdict(cfg), "rules": [asdict(r) for r in rules]}
        self.rules_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def load_schedules(self) -> List[Dict[str, str]]:
        if not self.schedule_file.exists():
            return []
        return json.loads(self.schedule_file.read_text(encoding="utf-8"))

    def save_schedules(self, items: List[Dict[str, str]]):
        self.schedule_file.write_text(json.dumps(items, indent=2), encoding="utf-8")


# ---------------------- Scheduler ----------------------
class SimpleScheduler:
    def __init__(self, app: "CleanerApp"):
        self.app = app
        self.tasks: List[Dict[str, str]] = app.store.load_schedules()
        self._h: Optional[int] = None

    def start(self):
        self.stop()
        self._tick()

    def stop(self):
        if self._h is not None:
            try:
                self.app.root.after_cancel(self._h)
            except Exception:
                pass
            self._h = None

    def add(self, name: str, action: str, time_str: str):
        self.tasks.append({"name": name, "action": action, "time": time_str})
        self.app.store.save_schedules(self.tasks)
        self.app._refresh_schedule_list()

    def remove(self, idx: int):
        if 0 <= idx < len(self.tasks):
            self.tasks.pop(idx)
            self.app.store.save_schedules(self.tasks)
            self.app._refresh_schedule_list()

    def _tick(self):
        now = datetime.now()
        for t in self.tasks:
            try:
                hh, mm = [int(x) for x in t.get("time","00:00").split(":",1)]
                target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
                if now >= target and now - target < timedelta(seconds=30):
                    self._run_action(t.get("action",""))
            except Exception:
                continue
        self._h = self.app.root.after(15_000, self._tick)
        self.app.register_after(self._h)

    def _run_action(self, action: str):
        a = action.lower().strip()
        if a == "scan":
            self.app.scan_async()
        elif a == "clean":
            self.app.clean_async()
        elif a == "purge_pip":
            self.app.purge_pip_cache_async()
        elif a == "purge_npm":
            self.app.purge_npm_cache_async()
        else:
            self.app._log_to_ui(f"Unknown scheduled action: {action}")


class ExternalPurges:
    @staticmethod
    def purge_pip_cache(log: Callable[[str], None]) -> None:
        try:
            os.system("pip cache purge >NUL 2>&1" if is_windows() else "pip cache purge >/dev/null 2>&1")
        except Exception:
            pass
        dirs: List[Path] = []
        if is_windows():
            dirs.append(Path.home()/"AppData/Local/pip/Cache")
        elif is_macos():
            dirs.append(Path("/Library/Caches/pip"))
            dirs.append(Path.home()/"Library/Caches/pip")
        else:
            dirs.append(Path.home()/".cache/pip")
        removed = 0
        for d in dirs:
            if d.exists():
                try:
                    shutil.rmtree(d, ignore_errors=True)
                    removed += 1
                except Exception as e:
                    log(f"pip cache: failed on {d}: {e}")
        log(f"pip cache: cleaned {removed} location(s)")

    @staticmethod
    def purge_npm_cache(log: Callable[[str], None]) -> None:
        try:
            os.system("npm cache clean --force >NUL 2>&1" if is_windows() else "npm cache clean --force >/dev/null 2>&1")
        except Exception:
            pass
        dirs: List[Path] = []
        if is_windows():
            dirs.append(Path.home()/"AppData/Roaming/npm-cache")
        elif is_macos():
            dirs.append(Path.home()/"Library/Caches/npm")
        else:
            dirs.extend([Path.home()/".npm", Path.home()/".cache/npm"])
        removed = 0
        for d in dirs:
            if d.exists():
                try:
                    shutil.rmtree(d, ignore_errors=True)
                    removed += 1
                except Exception as e:
                    log(f"npm cache: failed on {d}: {e}")
        log(f"npm cache: cleaned {removed} location(s)")


# ---------------------- GUI ----------------------
class CleanerApp(ShutdownMixin):
    def __init__(self, root: tk.Tk):
        self._setup_shutdown(root, log_path=DEFAULT_LOG)
        self.root.title(f"{APP_NAME} — v{APP_VERSION}")
        if _HAS_TTKB:
            Style(theme="superhero")
        self.store = ConfigStore()
        self.cfg, self.rules = self.store.load()
        self.engine = CleanerEngine(self.cfg)
        self.scan_results: List[ScanResult] = []
        self.scheduler = SimpleScheduler(self)
        self._make_ui()
        self.scheduler.start()
        self.age_off_logs()

    # UI Build
    def _make_ui(self):
        self.root.geometry("1180x760")
        outer = ttk.Frame(self.root, padding=8)
        outer.pack(fill=tk.BOTH, expand=True)

        # Toolbar
        tb = ttk.Frame(outer)
        tb.pack(fill=tk.X, pady=(0,6))
        self.dry_var = tk.BooleanVar(value=self.cfg.dry_run)
        btn_dry = ttk.Checkbutton(tb, text="Dry Run", variable=self.dry_var, command=self._on_toggle_dry)
        btn_dry.pack(side=tk.LEFT)
        Tooltip(btn_dry, "Simulate actions without modifying files.")

        self.recycle_only_var = tk.BooleanVar(value=self.cfg.hard_recycle_only)
        btn_ro = ttk.Checkbutton(tb, text="Hard Recycle-only", variable=self.recycle_only_var, command=self._on_toggle_recycle_only)
        btn_ro.pack(side=tk.LEFT, padx=(8,0))
        Tooltip(btn_ro, "Force Recycle Bin for all deletions; disables quarantine.")

        b_scan = ttk.Button(tb, text="Scan", command=self.scan_async, bootstyle="info")
        b_scan.pack(side=tk.LEFT, padx=6); Tooltip(b_scan, "Enumerate files matching rules.")
        b_clean = ttk.Button(tb, text="Clean", command=self.clean_async, bootstyle="success")
        b_clean.pack(side=tk.LEFT); Tooltip(b_clean, "Apply actions to scanned files.")
        b_pause = ttk.Button(tb, text="Pause/Resume", command=self.pause_resume, bootstyle="secondary")
        b_pause.pack(side=tk.LEFT, padx=(6,0)); Tooltip(b_pause, "Temporarily pause background workers.")
        b_cancel = ttk.Button(tb, text="Cancel", command=self.cancel_ops, bootstyle="danger")
        b_cancel.pack(side=tk.LEFT); Tooltip(b_cancel, "Request immediate stop of active workers.")

        ttk.Separator(tb, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)
        b_pip = ttk.Button(tb, text="Purge pip cache", command=self.purge_pip_cache_async, bootstyle="warning")
        b_pip.pack(side=tk.LEFT); Tooltip(b_pip, "Clear pip caches (CLI + folders).")
        b_npm = ttk.Button(tb, text="Purge npm cache", command=self.purge_npm_cache_async, bootstyle="warning")
        b_npm.pack(side=tk.LEFT, padx=(6,0)); Tooltip(b_npm, "Clean npm caches (force mode).")
        b_q = ttk.Button(tb, text="Open Quarantine", command=self.open_quarantine, bootstyle="secondary")
        b_q.pack(side=tk.RIGHT); Tooltip(b_q, "Open the quarantine folder in your OS file manager.")

        # Notebook
        nb = ttk.Notebook(outer)
        nb.pack(fill=tk.BOTH, expand=True)
        self.nb = nb

        tab_over = ttk.Frame(nb)
        nb.add(tab_over, text="Overview")
        self._build_overview(tab_over)

        tab_rules = ttk.Frame(nb)
        nb.add(tab_rules, text="Rules")
        self._build_rules(tab_rules)

        tab_sched = ttk.Frame(nb)
        nb.add(tab_sched, text="Scheduler")
        self._build_scheduler(tab_sched)

        tab_logs = ttk.Frame(nb)
        nb.add(tab_logs, text="Logs")
        self._build_logs(tab_logs)

        # Bottom status bar with progress + inline last log
        sb = ttk.Frame(outer)
        sb.pack(fill=tk.X, pady=(6,0))
        self.status_left = ttk.Label(sb, text="Ready")
        self.status_left.pack(side=tk.LEFT)
        self.status_center = ttk.Label(sb, text="")
        self.status_center.pack(side=tk.LEFT, padx=12)
        self.prg = ttk.Progressbar(sb, mode="determinate", length=220, bootstyle="info")
        self.prg.pack(side=tk.RIGHT)
        self.status_right = ttk.Label(sb, text="")
        self.status_right.pack(side=tk.RIGHT, padx=12)

    def _build_overview(self, parent):
        top = ttk.Frame(parent)
        top.pack(fill=tk.X, padx=4, pady=4)
        self.lbl_status = ttk.Label(top, text="Ready")
        self.lbl_status.pack(side=tk.LEFT)
        if psutil:
            self.lbl_disk = ttk.Label(top, text="")
            self.lbl_disk.pack(side=tk.RIGHT)
            self.register_after(self.root.after(1000, self._refresh_disk))

        cols = ("rule", "count", "size")
        tv = ttk.Treeview(parent, columns=cols, show="headings", height=18)
        for c, w in zip(cols, (380, 120, 160)):
            tv.heading(c, text=c.capitalize())
            tv.column(c, width=w, anchor=tk.W)
        tv.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        self.tv_results = tv

        foot = ttk.Frame(parent)
        foot.pack(fill=tk.X, padx=4, pady=(0,4))
        self.lbl_total = ttk.Label(foot, text="Total: 0 files, 0 B")
        self.lbl_total.pack(side=tk.RIGHT)

    def _build_rules(self, parent):
        container = ttk.Panedwindow(parent, orient=tk.HORIZONTAL)
        container.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        left = ttk.Frame(container)
        right = ttk.Frame(container)
        container.add(left, weight=2)
        container.add(right, weight=3)

        self.lst_rules = ttk.Treeview(left, columns=("name","path","age","action","enabled"), show="headings", height=20)
        for c, w in ("name", 240), ("path", 420), ("age", 60), ("action", 100), ("enabled", 80):
            self.lst_rules.heading(c, text=c.capitalize()); self.lst_rules.column(c, width=w, anchor=tk.W)
        self.lst_rules.pack(fill=tk.BOTH, expand=True)
        self.lst_rules.bind("<<TreeviewSelect>>", self._on_rule_select)
        self._refresh_rule_list()

        ed = ttk.LabelFrame(right, text="Rule Editor")
        ed.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        self.var_name = tk.StringVar()
        self.var_path = tk.StringVar()
        self.var_patterns = tk.StringVar()
        self.var_age = tk.IntVar(value=0)
        self.var_action = tk.StringVar(value="quarantine")
        self.var_enabled = tk.BooleanVar(value=True)
        self.var_rm_empty = tk.BooleanVar(value=True)

        grid = ttk.Frame(ed)
        grid.pack(fill=tk.X, padx=8, pady=8)
        r = 0
        for label, var, wid, tip in (
            ("Name", self.var_name, 36, "Unique label for this rule"),
            ("Path", self.var_path, 48, "Base directory to scan"),
            ("Patterns (comma)", self.var_patterns, 48, "Glob patterns relative to Path"),
        ):
            lbl = ttk.Label(grid, text=label); lbl.grid(row=r, column=0, sticky="w", pady=4)
            ent = ttk.Entry(grid, textvariable=var, width=wid)
            ent.grid(row=r, column=1, sticky="ew", pady=4)
            if label == "Path":
                btn = ttk.Button(grid, text="…", width=3, command=self._pick_path, bootstyle="secondary")
                btn.grid(row=r, column=2, padx=4)
                Tooltip(btn, "Pick a folder")
            Tooltip(ent, tip)
            r += 1
        ttk.Label(grid, text="Min age (days)").grid(row=r, column=0, sticky="w", pady=4)
        sp = ttk.Spinbox(grid, from_=0, to=3650, textvariable=self.var_age, width=6)
        sp.grid(row=r, column=1, sticky="w", pady=4); Tooltip(sp, "Only files older than N days")
        r += 1
        ttk.Label(grid, text="Action").grid(row=r, column=0, sticky="w", pady=4)
        cmb = ttk.Combobox(grid, values=["quarantine","delete","recycle"], textvariable=self.var_action, state="readonly", width=14)
        cmb.grid(row=r, column=1, sticky="w", pady=4); Tooltip(cmb, "What to do with matched files")
        r += 1
        chk1 = ttk.Checkbutton(grid, text="Enabled", variable=self.var_enabled)
        chk1.grid(row=r, column=0, sticky="w", pady=4); Tooltip(chk1, "Include this rule when scanning")
        chk2 = ttk.Checkbutton(grid, text="Remove empty directories", variable=self.var_rm_empty)
        chk2.grid(row=r, column=1, sticky="w", pady=4); Tooltip(chk2, "After actions, remove empty folders")

        # Stacked action groups (vertical)
        groups = ttk.Frame(ed)
        groups.pack(fill=tk.X, padx=8, pady=(8,8))

        # Primary CRUD group
        g1 = ttk.Labelframe(groups, text="Rule Actions")
        g1.pack(fill=tk.X, pady=6)
        b_new = ttk.Button(g1, text="New", command=self.add_rule_dialog, bootstyle="secondary")
        b_new.pack(fill=tk.X, pady=2); Tooltip(b_new, "Clear the editor to add a new rule")
        b_update = ttk.Button(g1, text="Update", command=self.update_rule_from_form, bootstyle="info")
        b_update.pack(fill=tk.X, pady=2); Tooltip(b_update, "Save changes to the selected rule or add a new one")
        b_del = ttk.Button(g1, text="Delete", command=self.delete_selected_rule, bootstyle="danger")
        b_del.pack(fill=tk.X, pady=2); Tooltip(b_del, "Remove the selected rule")

        # Presets group
        g2 = ttk.Labelframe(groups, text="Presets")
        g2.pack(fill=tk.X, pady=6)
        b_os = ttk.Button(g2, text="Add OS Cache Rules", command=self.add_os_rules, bootstyle="warning")
        b_os.pack(fill=tk.X, pady=2); Tooltip(b_os, "Add Windows/macOS/Linux cache targets")
        b_br = ttk.Button(g2, text="Add Browser Rules", command=self.add_browser_rules, bootstyle="warning")
        b_br.pack(fill=tk.X, pady=2); Tooltip(b_br, "Add Chrome/Edge/Firefox profile caches")

        # Config group
        g3 = ttk.Labelframe(groups, text="Configuration")
        g3.pack(fill=tk.X, pady=6)
        b_save = ttk.Button(g3, text="Save Rules", command=self.save_rules, bootstyle="success")
        b_save.pack(fill=tk.X, pady=2); Tooltip(b_save, "Persist rules and settings to clean_rules.json")

    def _build_scheduler(self, parent):
        wrap = ttk.Frame(parent)
        wrap.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        self.tbl_sched = ttk.Treeview(wrap, columns=("name","action","time"), show="headings", height=14)
        for c, w in ("name", 260), ("action", 160), ("time", 120):
            self.tbl_sched.heading(c, text=c.capitalize()); self.tbl_sched.column(c, width=w, anchor=tk.W)
        self.tbl_sched.pack(fill=tk.BOTH, expand=True)

        form = ttk.Frame(wrap)
        form.pack(fill=tk.X, pady=(8,0))
        self.s_name = tk.StringVar()
        self.s_action = tk.StringVar(value="scan")
        self.s_time = tk.StringVar(value="02:30")
        ttk.Label(form, text="Name").grid(row=0, column=0, sticky="w")
        e1 = ttk.Entry(form, textvariable=self.s_name, width=30); e1.grid(row=0, column=1, sticky="w", padx=6); Tooltip(e1, "Human-friendly label")
        ttk.Label(form, text="Action").grid(row=0, column=2, sticky="w")
        c1 = ttk.Combobox(form, values=["scan","clean","purge_pip","purge_npm"], textvariable=self.s_action, state="readonly", width=14)
        c1.grid(row=0, column=3, sticky="w", padx=6); Tooltip(c1, "What to run at the scheduled time")
        ttk.Label(form, text="Time (HH:MM)").grid(row=0, column=4, sticky="w")
        e2 = ttk.Entry(form, textvariable=self.s_time, width=10); e2.grid(row=0, column=5, sticky="w", padx=6); Tooltip(e2, "24h format, local time")
        b_add = ttk.Button(form, text="Add", command=self._add_schedule, bootstyle="success")
        b_add.grid(row=0, column=6, padx=6); Tooltip(b_add, "Create a daily schedule")
        b_rm = ttk.Button(form, text="Remove Selected", command=self._remove_schedule, bootstyle="danger")
        b_rm.grid(row=0, column=7); Tooltip(b_rm, "Delete the highlighted schedule")

        self._refresh_schedule_list()

    def _build_logs(self, parent):
        self.txt_log = tk.Text(parent, wrap="word", height=20)
        self.txt_log.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        self._log_to_ui(f"{APP_NAME} started. Version {APP_VERSION}")

    # Toolbar actions
    def _on_toggle_dry(self):
        self.cfg.dry_run = bool(self.dry_var.get())
        self._toast("Dry run is ON" if self.cfg.dry_run else "Dry run is OFF")
        self._log_to_ui(f"Dry run set to {self.cfg.dry_run}")

    def _on_toggle_recycle_only(self):
        self.cfg.hard_recycle_only = bool(self.recycle_only_var.get())
        self._toast("Recycle-only enforced")
        self._log_to_ui(f"Hard Recycle-only set to {self.cfg.hard_recycle_only}")

    def pause_resume(self):
        if self.engine._pause.is_set():
            self.engine.toggle_pause(False)
            self._toast("Resumed")
            self.lbl_status.config(text="Running…")
            self._status("Running…")
        else:
            self.engine.toggle_pause(True)
            self._toast("Paused")
            self.lbl_status.config(text="Paused")
            self._status("Paused")

    def cancel_ops(self):
        self.engine.stop()
        self._toast("Cancel requested")
        self._status("Cancelling…")
        self._log_to_ui("Cancel requested. Workers will stop soon.")

    # Async ops
    def scan_async(self):
        self.engine._stop.clear()
        self.lbl_status.config(text="Scanning…")
        self._status("Scanning…")
        self._progress_pulse()
        t = threading.Thread(target=self._scan_worker, daemon=True)
        t.start(); self.register_thread(t)

    def clean_async(self):
        if not self.scan_results:
            messagebox.showinfo(APP_NAME, "Run a Scan first.")
            return
        self.engine._stop.clear()
        self.lbl_status.config(text="Cleaning…")
        self._status("Cleaning…")
        self._progress_pulse()
        t = threading.Thread(target=self._clean_worker, daemon=True)
        t.start(); self.register_thread(t)

    def purge_pip_cache_async(self):
        t = threading.Thread(target=lambda: ExternalPurges.purge_pip_cache(self._log_to_ui), daemon=True)
        t.start(); self.register_thread(t)

    def purge_npm_cache_async(self):
        t = threading.Thread(target=lambda: ExternalPurges.purge_npm_cache(self._log_to_ui), daemon=True)
        t.start(); self.register_thread(t)

    def add_browser_rules(self):
        added = 0
        for r in browser_cache_rules():
            if all(existing.name != r.name for existing in self.rules):
                self.rules.append(r); added += 1
        self._refresh_rule_list()
        self._toast(f"Added {added} browser rule(s)")
        self._log_to_ui(f"Added {added} browser cache rule(s)")

    def add_os_rules(self):
        added = 0
        for r in os_specific_rules():
            if all(existing.name != r.name for existing in self.rules):
                self.rules.append(r); added += 1
        self._refresh_rule_list()
        self._toast(f"Added {added} OS rule(s)")
        self._log_to_ui(f"Added {added} OS cache rule(s)")

    def _scan_worker(self):
        self.scan_results.clear()
        total_files = 0
        total_bytes = 0
        for rule in self.rules:
            if self.engine._stop.is_set():
                break
            res = self.engine.enumerate_rule(rule)
            self.scan_results.append(res)
            total_files += len(res.files)
            total_bytes += res.total_size
            self._log_to_ui(f"Rule '{rule.name}': {len(res.files)} files, {human_bytes(res.total_size)}")
        self._refresh_results_tree()
        self.lbl_status.config(text="Scan complete")
        self._status("Scan complete")
        self._progress_stop()
        self.lbl_total.config(text=f"Total: {total_files} files, {human_bytes(total_bytes)}")

    def _clean_worker(self):
        deleted_total = 0
        freed_total = 0
        for res in self.scan_results:
            if self.engine._stop.is_set():
                break
            d, b = self.engine.act_on_files(res, self._log_to_ui)
            deleted_total += d
            freed_total += b
            if res.rule.remove_empty_dirs:
                try:
                    self.engine.cleanup_empty_dirs(res.rule.resolve_base())
                except Exception:
                    pass
            self._log_to_ui(f"Cleaned '{res.rule.name}': {d} files")
        done_text = "Cancelled" if self.engine._stop.is_set() else "Clean complete"
        self.lbl_status.config(text=done_text)
        self._status(f"{done_text} — Freed ~{human_bytes(freed_total)}")
        self._progress_stop()
        self._log_to_ui(f"DONE. Freed approx {human_bytes(freed_total)} (dry_run={self.cfg.dry_run})")

    def _refresh_results_tree(self):
        tv = self.tv_results
        for i in tv.get_children():
            tv.delete(i)
        for res in self.scan_results:
            tv.insert("", tk.END, values=(res.rule.name, len(res.files), human_bytes(res.total_size)))

    def _refresh_rule_list(self):
        tv = self.lst_rules
        for i in tv.get_children():
            tv.delete(i)
        for idx, r in enumerate(self.rules):
            tv.insert("", tk.END, iid=str(idx), values=(r.name, r.path, r.min_age_days, r.action, r.enabled))

    def _on_rule_select(self, _):
        sel = self.lst_rules.selection()
        if not sel:
            return
        idx = int(sel[0])
        r = self.rules[idx]
        self.var_name.set(r.name)
        self.var_path.set(r.path)
        self.var_patterns.set(", ".join(r.patterns))
        self.var_age.set(r.min_age_days)
        self.var_action.set(r.action)
        self.var_enabled.set(r.enabled)
        self.var_rm_empty.set(r.remove_empty_dirs)

    def _pick_path(self):
        p = filedialog.askdirectory(initialdir=str(Path.home()))
        if p:
            self.var_path.set(p)

    def add_rule_dialog(self):
        self.var_name.set(""); self.var_path.set("")
        self.var_patterns.set("*"); self.var_age.set(0)
        self.var_action.set("quarantine"); self.var_enabled.set(True)
        self.var_rm_empty.set(True)

    def update_rule_from_form(self):
        name = self.var_name.get().strip()
        if not name:
            messagebox.showerror(APP_NAME, "Rule name required")
            return
        rule = PathRule(
            name=name,
            path=self.var_path.get().strip(),
            patterns=[s.strip() for s in self.var_patterns.get().split(',') if s.strip()],
            min_age_days=int(self.var_age.get()),
            action=self.var_action.get(),
            enabled=bool(self.var_enabled.get()),
            remove_empty_dirs=bool(self.var_rm_empty.get()),
        )
        sel = self.lst_rules.selection()
        if sel:
            idx = int(sel[0]); self.rules[idx] = rule
        else:
            self.rules.append(rule)
        self._refresh_rule_list()
        self._toast("Rule saved")
        self._log_to_ui(f"Rule saved: {rule.name}")

    def delete_selected_rule(self):
        sel = self.lst_rules.selection()
        if not sel:
            return
        idx = int(sel[0])
        rule = self.rules.pop(idx)
        self._refresh_rule_list()
        self._toast("Rule deleted")
        self._log_to_ui(f"Rule deleted: {rule.name}")

    def save_rules(self):
        self.cfg.dry_run = bool(self.dry_var.get())
        self.cfg.hard_recycle_only = bool(self.recycle_only_var.get())
        self.store.save(self.cfg, self.rules)
        self._toast("Rules saved")
        self._log_to_ui("Rules saved to clean_rules.json")

    def open_quarantine(self):
        ensure_quarantine()
        path = str(QUARANTINE_DIR)
        if is_windows():
            os.startfile(path)  # type: ignore
        elif is_macos():
            os.system(f"open '{path}'")
        else:
            os.system(f"xdg-open '{path}'")

    def _refresh_disk(self):
        try:
            if psutil:
                base_path = Path.home()
                if is_windows():
                    base_path = Path(os.path.splitdrive(str(base_path))[0] + os.sep)
                usage = psutil.disk_usage(str(base_path))
                self.lbl_disk.config(text=f"Free: {human_bytes(usage.free)} / Total: {human_bytes(usage.total)}")
        finally:
            self.register_after(self.root.after(3000, self._refresh_disk))

    # Feedback helpers
    def _log_to_ui(self, msg: str):
        try:
            self.txt_log.insert(tk.END, msg)
            self.txt_log.see(tk.END)
            self.status_right.config(text=msg.strip()[:100])
        except Exception:
            pass
        try:
            logging.getLogger(APP_NAME).info(msg.strip())
        except Exception:
            pass

    def _status(self, s: str):
        try:
            self.status_left.config(text=s)
        except Exception:
            pass

    def _toast(self, s: str):
        try:
            self.status_center.config(text=s)
            self.root.after(2500, lambda: self.status_center.config(text=""))
        except Exception:
            pass

    def _progress_pulse(self):
        try:
            self.prg.config(mode="indeterminate")
            self.prg.start(12)
        except Exception:
            pass

    def _progress_stop(self):
        try:
            self.prg.stop()
            self.prg.config(mode="determinate", value=0)
        except Exception:
            pass

    # Scheduler helpers
    def _add_schedule(self):
        name = self.s_name.get().strip() or f"Task {len(self.scheduler.tasks)+1}"
        action = self.s_action.get().strip()
        time_str = self.s_time.get().strip()
        self.scheduler.add(name, action, time_str)
        self._toast(f"Scheduled: {name}")
        self._log_to_ui(f"Scheduled: {name} @ {time_str} → {action}")

    def _remove_schedule(self):
        sel = self.tbl_sched.selection()
        if not sel:
            return
        idx = int(sel[0])
        item = self.scheduler.tasks[idx]
        self.scheduler.remove(idx)
        self._toast("Schedule removed")
        self._log_to_ui(f"Removed schedule: {item.get('name')}")

    def _refresh_schedule_list(self):
        tv = self.tbl_sched
        if not hasattr(self, "tbl_sched"):
            return
        for i in tv.get_children():
            tv.delete(i)
        for idx, t in enumerate(self.scheduler.tasks):
            tv.insert("", tk.END, iid=str(idx), values=(t.get("name"), t.get("action"), t.get("time")))

    def age_off_logs(self):
        days = max(1, int(self.cfg.log_age_off_days))
        cutoff = time.time() - days*86400
        for p in LOGS_DIR.glob("*.log*"):
            try:
                if p.stat().st_mtime < cutoff:
                    p.unlink(missing_ok=True)
            except Exception:
                pass


def main():
    root = tk.Tk()
    app = CleanerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
