# Garbage Cleaner Pro

A rule‑based desktop cleaner for Windows/macOS/Linux built with **Tkinter** (+ optional **ttkbootstrap**). It safely reclaims disk space by scanning large, stale, or cache files and acting on them via **Quarantine**, **Recycle Bin**, or **Delete**. The app is responsive (background workers), supports **pause/cancel**, **scheduler**, **browser/OS cache presets**, and has a hardened shutdown strategy.

> Single‑file app: `garbage_cleaner_pro.py`

---

## ✨ Features

* **Rule Engine**: per‑path glob patterns, min‑age filter, per‑rule action (quarantine/delete/recycle), enable/disable, optional empty‑dir cleanup.
* **Safety First**: default **Dry Run**; caps on per‑rule and total deletes; quarantine to `~/.garbage_cleaner_quarantine`.
* **Recycle Bin**: via `send2trash` (optional). Global **Hard Recycle‑Only** mode forces recycle for all deletions.
* **Responsive UI**: scan/clean run in background threads; **Pause/Resume** and **Cancel** controls.
* **Presets**: one‑click **Browser Cache** (Chrome/Edge/Firefox profiles) and **OS‑specific caches** (Windows/macOS/Linux).
* **Package Manager Cleanups**: `pip` and `npm` cache purge actions.
* **Scheduler**: simple daily schedules for `scan`, `clean`, `purge_pip`, `purge_npm`.
* **Logging**: rotating logs in `./logs/` + age‑off (default 30 days).
* **Polished UX**: tooltips on controls, status/toast messages, bottom status bar with live log line and progress.
* **Robust Shutdown**: cancels timers, joins threads, flushes logs, and destroys the Tk root cleanly.

---

## 🧰 Requirements

* **Python**: 3.9+ (tested up to 3.12)
* **Standard lib**: Tkinter (usually included with Python on Windows/macOS; on some Linux distros install `python3-tk`).
* **Optional**:

  * [`ttkbootstrap`](https://github.com/israel-dryer/ttkbootstrap) (for modern theming)
  * [`psutil`](https://pypi.org/project/psutil/) (disk space in status bar)
  * [`send2trash`](https://pypi.org/project/Send2Trash/) (Recycle Bin integration)

Install extras:

```bash
pip install ttkbootstrap psutil send2trash
```

> Linux users may need: `sudo apt-get install python3-tk` (or the equivalent for your distro).

---

## 🚀 Run

```bash
python garbage_cleaner_pro.py
```

* The app starts in **Dry Run** mode. Click **Scan** to preview; click **Clean** only after reviewing results.
* Use **Hard Recycle‑Only** to force all deletions to go via the OS Recycle Bin (requires `send2trash`).

---

## 🧭 How It Works

### Rules

A **Rule** targets a base path and a set of glob patterns, with optional time and action constraints.

* **Path**: base directory to scan
* **Patterns**: comma‑separated globs (e.g., `**/*.tmp, **/__pycache__/*`)
* **Min Age (days)**: ignore files newer than N days
* **Action**: `quarantine` | `recycle` | `delete`
* **Remove empty directories**: after actions, remove now‑empty folders

You can create/edit rules in the **Rules** tab or store them on disk (see **Configuration Files** below).

### Presets

* **Browser Cache Rules**: detects per‑profile caches for Chrome/Edge/Firefox.
* **OS Cache Rules**: adds common caches for Windows/macOS/Linux (e.g., `~/Library/Caches` on macOS, `~/.cache` on Linux, `%LOCALAPPDATA%/Temp` on Windows).

### Actions & Safety

* **Dry Run**: simulates actions; no changes on disk.
* **Quarantine**: moves files to `~/.garbage_cleaner_quarantine/<RuleName>/...` so you can review/restore.
* **Recycle**: sends files to OS Recycle Bin (requires `send2trash`).
* **Delete**: permanently removes files (use sparingly; prefer Recycle/Quarantine).
* **Hard Recycle‑Only**: a global toggle that overrides all rules and enforces Recycle.
* **Caps**: defaults limit per‑rule (`max_delete_per_rule`) and overall (`max_total_delete`) deletions to avoid mistakes.

### Performance & UX

* **Background workers** keep the UI responsive.
* **Pause/Resume**: temporarily halt workers; **Cancel** stops them ASAP.
* **Status Bar**: left = activity, center = toast/quick feedback, right = last log line; progress bar pulses during long ops.

---

## 🗓️ Scheduler

Simple daily scheduler that runs actions at fixed local times (HH:MM).

* Supported actions: `scan`, `clean`, `purge_pip`, `purge_npm`
* Add/remove schedules in the **Scheduler** tab.
* Schedules are stored in `schedules.json` (see format below).

> The scheduler is in‑app; it triggers when the app is running. For OS‑level automation, consider a CLI wrapper with cron/Task Scheduler.

---

## 🗃️ Configuration Files

### `clean_rules.json`

Saved automatically from the **Rules** tab.

```json
{
  "config": {
    "dry_run": true,
    "quarantine_enabled": true,
    "follow_symlinks": false,
    "max_delete_per_rule": 50000,
    "max_total_delete": 200000,
    "log_age_off_days": 30,
    "hard_recycle_only": false
  },
  "rules": [
    {
      "name": "System TEMP",
      "path": "/tmp",
      "patterns": ["*"],
      "min_age_days": 1,
      "remove_empty_dirs": true,
      "action": "quarantine",
      "enabled": true
    }
  ]
}
```

### `schedules.json`

Created from the **Scheduler** tab.

```json
[
  { "name": "Nightly Scan", "action": "scan", "time": "02:00" },
  { "name": "Weekly npm purge", "action": "purge_npm", "time": "03:00" }
]
```

---

## 🔧 Controls Cheat‑Sheet

* **Dry Run**: simulate; nothing is deleted or moved
* **Hard Recycle‑Only**: force Recycle Bin; disables quarantine semantics
* **Scan**: enumerate files per rule (results shown in Overview)
* **Clean**: apply configured actions to the last scan
* **Pause/Resume**: halt/resume background work
* **Cancel**: stop active workers ASAP
* **Purge pip/npm cache**: run package manager cache cleanup (CLI + folder fallbacks)
* **Open Quarantine**: open quarantine folder in OS file manager

Rule Editor:

* **New / Update / Delete** (stacked, colored)
* **Add OS Cache Rules / Add Browser Rules** presets
* **Save Rules**: persist `clean_rules.json`

---

## 🧪 Tips & Best Practices

* Start with **Dry Run** and Presets; review counts/sizes before enabling **Clean**.
* Prefer **Recycle** or **Quarantine** over **Delete** unless you’re 100% sure.
* Use **Min Age** (e.g., 2–7 days) to avoid nuking active caches.
* Keep `max_delete_*` caps high enough to be useful but low enough to be safe.
* On CI/servers, consider headless operation (CLI wrapper) and cron.

---

## 🐛 Troubleshooting

* **Tkinter not found**: install your distro’s Tk package (e.g., `python3-tk`).
* **`send2trash` missing**: install via `pip install send2trash` or disable Recycle‑only.
* **Permission errors**: run as a user with access; avoid system folders requiring elevation.
* **Long paths/locked files**: the app skips files it cannot access; check the logs for skipped paths.
* **Linux Wayland issues**: if Tk windows behave oddly, try running under X11 (`XDG_SESSION_TYPE=x11`).

---

## 🧱 Security & Safety

* Never add system directories you don’t fully understand.
* Avoid `**/*` rules rooted at high‑level paths (e.g., `/` or `C:\`).
* Keep **Dry Run** on when editing rules; flip it off only after verifying.
* Quarantine grows over time—review and clear it periodically.

---

## 🛣️ Roadmap (ideas)

* Parallel delete worker pool with rate‑limiting
* Preview pane (sample files per rule)
* More presets: Brave/Opera, Yarn/pnpm, IDE caches
* CLI flags: `--scan`, `--clean`, `--recycle-only`, `--rules <file>`
* Tray mode + OS notifications

---

## 📄 License

**Propriatery**

---

## 🙌 Credits

* Built with Python’s standard **Tkinter** plus optional **ttkbootstrap** for modern styling.
* Uses **Send2Trash** for Recycle Bin support and **psutil** for disk telemetry.
