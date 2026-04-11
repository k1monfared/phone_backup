"""Phone Backup - simple terminal interface."""
import curses
import os
import subprocess
import sys
import threading
import time
import tty
import termios
from pathlib import Path
from datetime import datetime

from detector import detect_phones, detect_adb_device, detect_transfer_backend
from config_manager import (
    create_phone_config,
    load_phone_config,
)
from transfer import (
    TransferStats,
    transfer_folder,
)
import shutil


# --- USER-CONFIGURABLE PARAMETERS -------------------------------------------
BACKUP_BASE = Path.home() / "backup"
PHONES_DIR = Path(__file__).parent / "phones"
# -----------------------------------------------------------------------------


def format_size(size_bytes: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def format_eta(seconds: float) -> str:
    if seconds <= 0:
        return "--:--"
    seconds = int(seconds)
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60:02d}s"
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    return f"{hours}h {minutes:02d}m"


def open_in_editor(filepath: Path) -> None:
    """Open a file in the user's default editor."""
    editor = os.environ.get("EDITOR", "nano")
    cmd = [editor]
    basename = Path(editor).name
    if basename in ("code", "code-insiders", "subl", "atom", "zed"):
        cmd.append("--wait")
    cmd.append(str(filepath))
    subprocess.run(cmd)


# ---------------------------------------------------------------------------
# Main backup interface (curses)
# ---------------------------------------------------------------------------

def backup_ui(stdscr):
    """Main curses-based backup interface."""
    curses.curs_set(0)
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_GREEN, -1)
    curses.init_pair(2, curses.COLOR_YELLOW, -1)
    curses.init_pair(3, curses.COLOR_RED, -1)
    curses.init_pair(4, curses.COLOR_CYAN, -1)

    GREEN = curses.color_pair(1)
    YELLOW = curses.color_pair(2)
    RED = curses.color_pair(3)
    CYAN = curses.color_pair(4)
    BOLD = curses.A_BOLD
    DIM = curses.A_DIM
    REVERSE = curses.A_REVERSE

    # Detect phone
    phones = detect_phones()
    if not phones:
        stdscr.addstr(0, 0, "No phone detected.", RED | BOLD)
        stdscr.addstr(1, 0, "Connect a phone in file transfer mode and try again.")
        stdscr.addstr(3, 0, "Press any key to exit.")
        stdscr.refresh()
        stdscr.getch()
        return None

    phone = phones[0]
    phone_id = phone["phone_id"]
    display_name = phone["display_name"]

    # Detect transfer backend (show status while checking)
    stdscr.addstr(0, 0, f" Connected: {display_name}", BOLD | GREEN)
    stdscr.addstr(2, 0, " Detecting transfer backend...", DIM)
    stdscr.refresh()

    backend = detect_transfer_backend()
    adb_serial = None
    if backend == "adb":
        adb_serial = detect_adb_device()
    elif shutil.which("adb") and backend != "adb":
        stdscr.erase()
        stdscr.addstr(0, 0, f" Connected: {display_name}", BOLD | GREEN)
        stdscr.addstr(2, 0, " adb is available but your phone is not connected via USB debugging.", YELLOW)
        stdscr.addstr(3, 0, " Enabling USB debugging makes transfers 2-5x faster.")
        stdscr.addstr(5, 0, " To enable: Settings > Developer Options > USB Debugging > ON")
        stdscr.addstr(6, 0, " (If you don't see Developer Options: Settings > About Phone > tap Build Number 7 times)")
        stdscr.addstr(8, 0, " Then reconnect USB cable and accept the prompt on your phone.")
        stdscr.addstr(10, 0, " Press 'r' to retry adb detection, or any other key to continue.", DIM)
        stdscr.refresh()
        key = stdscr.getch()
        if key == ord("r") or key == ord("R"):
            adb_serial = detect_adb_device()
            if adb_serial:
                backend = "adb"

    backend_labels = {"adb": "adb (fastest)", "gio": "gio (fast)", "python": "python (slow)"}
    backend_label = backend_labels.get(backend, backend)

    PHONES_DIR.mkdir(parents=True, exist_ok=True)
    config = load_phone_config(phone_id, PHONES_DIR)
    if config is None:
        config = create_phone_config(
            phone_id=phone_id,
            display_name=display_name,
            mount_path=phone["mount_path"],
            phones_dir=PHONES_DIR,
            backup_base=BACKUP_BASE,
        )
        return ("edit", PHONES_DIR / f"{phone_id}.yaml")

    mount_path = phone["mount_path"]
    sync_entries = config.get("sync") or []
    move_entries = config.get("move") or []
    undecided = config.get("undecided") or []

    # Build items: list of (source, dest, checked, section)
    items = []
    for e in sync_entries:
        items.append({"source": e["source"], "dest": e["dest"], "checked": True, "section": "sync"})
    for e in move_entries:
        items.append({"source": e["source"], "dest": e["dest"], "checked": True, "section": "move"})
    config_changed = False

    # Background folder size scanning (single thread to avoid overwhelming MTP)
    folder_sizes = {}

    def scan_all_folder_sizes():
        for it in items:
            source = it["source"]
            path = mount_path / source
            count = 0
            total = 0
            if path.exists():
                try:
                    for f in path.rglob("*"):
                        if f.is_file() and not f.name.startswith(".tmp_"):
                            count += 1
                            try:
                                total += f.stat().st_size
                            except OSError:
                                pass
                except OSError:
                    pass
            folder_sizes[source] = (count, total)

    threading.Thread(target=scan_all_folder_sizes, daemon=True).start()

    def save_config_from_items():
        """Save current item assignments back to the YAML config."""
        from config_manager import save_phone_config
        config["sync"] = [{"source": it["source"], "dest": it["dest"]}
                          for it in items if it["section"] == "sync"]
        config["move"] = [{"source": it["source"], "dest": it["dest"]}
                          for it in items if it["section"] == "move"]
        save_phone_config(config, PHONES_DIR)

    def reorder_items():
        """Re-sort: sync first then move, grouped by dest within each."""
        sync = sorted([it for it in items if it["section"] == "sync"], key=lambda x: x["dest"])
        move = sorted([it for it in items if it["section"] == "move"], key=lambda x: x["dest"])
        items.clear()
        items.extend(sync)
        items.extend(move)

    reorder_items()

    if not items:
        stdscr.addstr(0, 0, f"Connected: {display_name}", BOLD)
        stdscr.addstr(2, 0, "No folders configured for sync or move.", YELLOW)
        stdscr.addstr(3, 0, f"Run 'backup_phone config' to set up folders.")
        stdscr.addstr(5, 0, "Press any key to exit.")
        stdscr.refresh()
        stdscr.getch()
        return None

    # UI state
    cursor = 0
    tab = 0  # 0 = folder list, 1 = actions
    scroll_offset = 0
    action_idx = 0  # 0=start, 1=edit config, 2=quit
    actions = ["Start Backup", "Edit Config", "Quit"]

    while True:
        stdscr.erase()
        max_y, max_x = stdscr.getmaxyx()

        # Header
        header = f" Connected: {display_name} | Transfer: {backend_label}"
        stdscr.addstr(0, 0, header[:max_x - 1], BOLD | GREEN)

        if undecided:
            warn = f" ! {len(undecided)} folders in 'undecided' - run: backup_phone config"
            stdscr.addstr(1, 0, warn[:max_x - 1], YELLOW)

        # Section headers
        row = 3
        sync_items = [i for i, it in enumerate(items) if it["section"] == "sync"]
        move_items = [i for i, it in enumerate(items) if it["section"] == "move"]

        # Available rows for the list
        list_top = row
        list_bottom = max_y - 5  # reserve bottom for actions + status
        visible_rows = list_bottom - list_top

        # Build display lines: (type, index_or_none, text, attr)
        display_lines = []
        last_section = None
        last_dest = None
        for i, it in enumerate(items):
            section = it["section"]
            if section != last_section:
                if section == "sync":
                    display_lines.append(("header", None,
                        f"  Sync ({len(sync_items)} folders, keep on phone)", CYAN | BOLD, ""))
                else:
                    display_lines.append(("header", None,
                        f"  Move ({len(move_items)} folders, delete from phone)", CYAN | BOLD, ""))
                last_section = section
                last_dest = None
            if it["dest"] != last_dest:
                display_lines.append(("group", None, f"    {it['dest']}/", DIM, ""))
                last_dest = it["dest"]
            check = "[x]" if it["checked"] else "[ ]"
            size_info = folder_sizes.get(it["source"])
            if size_info is not None:
                cnt, byt = size_info
                size_str = f"{cnt} files, {format_size(byt)}"
            else:
                size_str = "..."
            display_lines.append(("item", i, f"      {check} {it['source']}", curses.A_NORMAL, size_str))

        # Find which display line the cursor is on
        cursor_display_line = 0
        for dl_idx, (dtype, item_idx, _, _, _) in enumerate(display_lines):
            if dtype == "item" and item_idx == cursor:
                cursor_display_line = dl_idx
                break

        # Adjust scroll
        if cursor_display_line < scroll_offset:
            scroll_offset = cursor_display_line
        if cursor_display_line >= scroll_offset + visible_rows:
            scroll_offset = cursor_display_line - visible_rows + 1

        # Render visible lines
        rendered_row = list_top
        for dl_idx in range(scroll_offset, len(display_lines)):
            if rendered_row >= list_bottom:
                break
            dtype, item_idx, text, attr, size_str = display_lines[dl_idx]
            is_cursor = dtype == "item" and tab == 0 and item_idx == cursor
            if is_cursor:
                attr = REVERSE

            if size_str:
                # Right-align size string
                pad = max_x - 1 - len(text) - len(size_str) - 1
                if pad > 0:
                    line_str = text + " " * pad + size_str
                else:
                    line_str = text
                stdscr.addstr(rendered_row, 0, line_str[:max_x - 1], attr)
            else:
                stdscr.addstr(rendered_row, 0, text[:max_x - 1], attr)
            rendered_row += 1

        # Actions bar
        action_row = max_y - 3
        stdscr.addstr(action_row - 1, 0, "-" * (max_x - 1), DIM)

        for ai, act in enumerate(actions):
            col = 2 + ai * 20
            if col >= max_x - 1:
                break
            attr = curses.A_NORMAL
            if tab == 1 and ai == action_idx:
                attr = REVERSE
            prefix = "> " if tab == 1 and ai == action_idx else "  "
            stdscr.addstr(action_row, col, f"{prefix}{act}"[:max_x - col - 1], attr)

        # Help line
        help_row = max_y - 1
        n_checked = sum(1 for it in items if it["checked"])
        help_text = f" {n_checked}/{len(items)} selected | arrows:move  space:toggle  s:to-sync  m:to-move  a:all  n:none  tab:actions  q:quit"
        stdscr.addstr(help_row, 0, help_text[:max_x - 1], DIM)

        stdscr.refresh()

        # Input
        key = stdscr.getch()

        if key == ord("q") or key == ord("Q"):
            return None
        elif key == ord("\t") or key == 9:
            tab = 1 - tab
        elif key == curses.KEY_UP:
            if tab == 0:
                cursor = max(0, cursor - 1)
            else:
                pass
        elif key == curses.KEY_DOWN:
            if tab == 0:
                cursor = min(len(items) - 1, cursor + 1)
            else:
                pass
        elif key == curses.KEY_LEFT:
            if tab == 1:
                action_idx = max(0, action_idx - 1)
        elif key == curses.KEY_RIGHT:
            if tab == 1:
                action_idx = min(len(actions) - 1, action_idx + 1)
        elif key == ord(" "):
            if tab == 0 and 0 <= cursor < len(items):
                items[cursor]["checked"] = not items[cursor]["checked"]
        elif key == ord("a"):
            for it in items:
                it["checked"] = True
        elif key == ord("n"):
            for it in items:
                it["checked"] = False
        elif key == ord("s"):
            if tab == 0 and 0 <= cursor < len(items) and items[cursor]["section"] != "sync":
                items[cursor]["section"] = "sync"
                source = items[cursor]["source"]
                reorder_items()
                cursor = next(i for i, it in enumerate(items) if it["source"] == source)
                config_changed = True
                save_config_from_items()
        elif key == ord("m"):
            if tab == 0 and 0 <= cursor < len(items) and items[cursor]["section"] != "move":
                items[cursor]["section"] = "move"
                source = items[cursor]["source"]
                reorder_items()
                cursor = next(i for i, it in enumerate(items) if it["source"] == source)
                config_changed = True
                save_config_from_items()
        elif key in (ord("\n"), ord("\r"), curses.KEY_ENTER, 10, 13):
            if tab == 1:
                if action_idx == 0:  # Start Backup
                    break
                elif action_idx == 1:  # Edit Config
                    return ("edit", PHONES_DIR / f"{phone_id}.yaml")
                elif action_idx == 2:  # Quit
                    return None
            elif tab == 0:
                # Enter on a folder item toggles it
                if 0 <= cursor < len(items):
                    items[cursor]["checked"] = not items[cursor]["checked"]

    # --- Run backup ---
    selected = [it for it in items if it["checked"]]
    if not selected:
        stdscr.erase()
        stdscr.addstr(0, 0, "No folders selected. Press any key.")
        stdscr.refresh()
        stdscr.getch()
        return None

    # Build transfer tasks
    backup_root = Path(config["backup_root"])
    today = datetime.now().strftime("%Y-%m-%d")
    tasks = []
    for it in selected:
        src = mount_path / it["source"]
        if it["section"] == "move":
            dst = backup_root / "move" / today / it["dest"]
        else:
            dst = backup_root / "sync" / it["dest"]
        delete = it["section"] == "move"
        tasks.append((src, dst, delete))

    # Use cached folder sizes from background scan instead of a slow pre-scan
    total_files = 0
    total_bytes = 0
    for it in selected:
        cached = folder_sizes.get(it["source"])
        if cached:
            total_files += cached[0]
            total_bytes += cached[1]

    stats = TransferStats(total_files=total_files, total_bytes=total_bytes)
    BACKUP_BASE.mkdir(parents=True, exist_ok=True)

    # Check disk space
    import shutil as _shutil
    disk = _shutil.disk_usage(str(BACKUP_BASE))
    free_gb = disk.free / (1024 ** 3)
    needed_gb = total_bytes / (1024 ** 3) if total_bytes > 0 else 0
    if free_gb < 1.0 or (needed_gb > 0 and free_gb < needed_gb * 1.1):
        stdscr.erase()
        stdscr.addstr(0, 0, " Low disk space!", RED | BOLD)
        stdscr.addstr(2, 2, f"Free: {free_gb:.1f} GB")
        if needed_gb > 0:
            stdscr.addstr(3, 2, f"Estimated needed: {needed_gb:.1f} GB")
        stdscr.addstr(5, 2, "Press 'c' to continue anyway, or any other key to cancel.")
        stdscr.refresh()
        key = stdscr.getch()
        if key != ord("c") and key != ord("C"):
            return None

    # Transfer log
    log_path = PHONES_DIR / f"{phone_id}.transfer.log"
    log_file = open(log_path, "a")
    log_file.write(f"\n--- Transfer started {datetime.now().isoformat()} ---\n")

    log_lines = []
    cancel = threading.Event()
    skip_event = threading.Event()
    defer_event = threading.Event()

    def on_progress():
        pass  # We poll stats from the main loop

    def on_log(msg):
        timestamp = datetime.now().strftime("%H:%M:%S")
        line = f"[{timestamp}] {msg}"
        log_file.write(line + "\n")
        log_file.flush()
        log_lines.append(line)
        if len(log_lines) > 100:
            log_lines.pop(0)

    def run_transfer():
        try:
            for src, dst, delete in tasks:
                if cancel.is_set():
                    on_log("CANCELLED by user")
                    break
                on_log(f"START {'MOVE' if delete else 'SYNC'} {src.name} -> {dst}")
                transfer_folder(
                    src_folder=src,
                    dst_folder=dst,
                    stats=stats,
                    delete_source=delete,
                    backend=backend,
                    adb_serial=adb_serial,
                    progress_callback=on_progress,
                    log_callback=on_log,
                    cancel_event=cancel,
                    skip_event=skip_event,
                    defer_event=defer_event,
                )
        except OSError as e:
            on_log(f"ERROR: {e}")
            if e.errno == 28:
                on_log("DISK FULL. Backup stopped.")
        log_file.write(f"--- Transfer finished {datetime.now().isoformat()} ---\n")
        log_file.close()

    worker = threading.Thread(target=run_transfer, daemon=True)
    worker.start()

    # Progress display loop
    stdscr.nodelay(True)
    while worker.is_alive():
        stdscr.erase()
        max_y, max_x = stdscr.getmaxyx()

        stdscr.addstr(0, 0, f" Backing up: {display_name} | {backend_label}", BOLD | GREEN)

        # Progress bar
        done = stats.files_done + stats.files_skipped
        pct = stats.percent_bytes
        eta = format_eta(stats.eta_seconds)

        bar_width = min(max_x - 4, 60)
        if stats.total_bytes > 0:
            filled = int(bar_width * pct / 100)
            bar = "#" * filled + "-" * (bar_width - filled)
            stdscr.addstr(2, 2, f"[{bar}] {pct:.0f}%")
            stdscr.addstr(3, 2, f"Files: {done} / {stats.total_files}  "
                                 f"({format_size(stats.bytes_done)} / {format_size(stats.total_bytes)})  "
                                 f"ETA: {eta}")
        else:
            stdscr.addstr(2, 2, f"Files: {done}  ({format_size(stats.bytes_done)})")

        if stats.current_file:
            # Poll temp file size for real-time progress with adb/gio backends
            copied = stats.current_file_copied
            if copied == 0 and stats.current_tmp_path:
                try:
                    copied = Path(stats.current_tmp_path).stat().st_size
                except OSError:
                    pass
            cur = f"Current: {stats.current_file} ({format_size(copied)} / {format_size(stats.current_file_bytes)})"
            stdscr.addstr(4, 2, cur[:max_x - 3])

        if stats.files_user_skipped > 0 or stats.files_deferred > 0:
            skip_info = f"Skipped: {stats.files_user_skipped}  Deferred: {stats.files_deferred}"
            stdscr.addstr(5, 2, skip_info[:max_x - 3], YELLOW)

        # Log tail
        log_start = 7
        visible = max_y - log_start - 2
        tail = log_lines[-visible:] if visible > 0 else []
        for li, line in enumerate(tail):
            r = log_start + li
            if r < max_y - 1:
                stdscr.addstr(r, 2, line[:max_x - 3], DIM)

        stdscr.addstr(max_y - 1, 0, " 's':skip file  'd':defer file  'c':cancel all", DIM)
        stdscr.refresh()

        key = stdscr.getch()
        if key == ord("c") or key == ord("C"):
            cancel.set()
        elif key == ord("s") or key == ord("S"):
            skip_event.set()
        elif key == ord("d") or key == ord("D"):
            defer_event.set()

        time.sleep(0.3)

    stdscr.nodelay(False)
    worker.join()

    # Write failure report if any files failed
    report_path = None
    if stats.failed_files:
        report_path = backup_root / f"failed_{today}_{datetime.now().strftime('%H%M%S')}.log"
        try:
            with open(report_path, "w") as f:
                f.write(f"Phone Backup Failure Report\n")
                f.write(f"Date: {datetime.now().isoformat()}\n")
                f.write(f"Phone: {display_name} ({phone_id})\n")
                f.write(f"Backend: {backend_label}\n")
                f.write(f"\n")
                f.write(f"Summary: {stats.files_done} copied, {stats.files_skipped} skipped, "
                        f"{stats.files_user_skipped} user-skipped, {stats.files_failed} failed\n")
                f.write(f"\nFailed files ({len(stats.failed_files)}):\n")
                for fp in stats.failed_files:
                    f.write(f"  {fp}\n")
        except OSError:
            report_path = None

    # Final summary
    stdscr.erase()
    stdscr.addstr(0, 0, " Backup complete", BOLD | GREEN)
    stdscr.addstr(2, 2, f"Copied:  {stats.files_done}")
    stdscr.addstr(3, 2, f"Skipped: {stats.files_skipped}")
    row = 4
    if stats.files_user_skipped:
        stdscr.addstr(row, 2, f"User-skipped: {stats.files_user_skipped} (will retry next run)", YELLOW)
        row += 1
    if stats.files_deferred:
        stdscr.addstr(row, 2, f"Deferred (retried at end): {stats.files_deferred}", DIM)
        row += 1
    if stats.files_failed:
        stdscr.addstr(row, 2, f"Failed:  {stats.files_failed} (retried once each)", RED)
        row += 1
        for fp in stats.failed_files[:10]:
            stdscr.addstr(row, 4, fp[:max_x - 5], RED)
            row += 1
        if len(stats.failed_files) > 10:
            stdscr.addstr(row, 4, f"... and {len(stats.failed_files) - 10} more", RED)
            row += 1
    if report_path:
        stdscr.addstr(row + 1, 2, f"Report: {report_path}", DIM)
        row += 2
    stdscr.addstr(row + 1, 0, " Press any key to exit.")
    stdscr.refresh()
    stdscr.getch()
    return None


# ---------------------------------------------------------------------------
# Config mode (arrow-key phone picker)
# ---------------------------------------------------------------------------

def _read_key():
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
        if ch == "\x1b":
            seq = sys.stdin.read(2)
            if seq == "[A":
                return "up"
            if seq == "[B":
                return "down"
            return "esc"
        if ch in ("\r", "\n"):
            return "enter"
        if ch in ("q", "Q", "\x03"):
            return "quit"
        if ch.isdigit():
            return ch
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _render_menu(entries, selected):
    total_lines = 3 + len(entries) * 3 + 3
    sys.stdout.write(f"\x1b[{total_lines}A")

    sys.stdout.write("\n  Phone Configs\n")
    sys.stdout.write("  " + "-" * 60 + "\n")
    for i, (cf, pid, name, ns, nm, nu, conn) in enumerate(entries):
        indicator = " * " if conn else "   "
        undecided_warn = f"  ({nu} undecided)" if nu > 0 else ""
        if i == selected:
            sys.stdout.write("\x1b[7m")
        sys.stdout.write(f"  {indicator}{i + 1}. {name}\x1b[K\n")
        sys.stdout.write(f"      sync: {ns}  move: {nm}{undecided_warn}\x1b[K\n")
        sys.stdout.write(f"      {cf.resolve()}\x1b[K\n")
        if i == selected:
            sys.stdout.write("\x1b[0m")
    sys.stdout.write("\n")
    if any(e[6] for e in entries):
        sys.stdout.write("  * = currently connected\n")
    else:
        sys.stdout.write("\n")
    sys.stdout.write("  arrows/number to select, Enter to edit, q to quit\x1b[K\n")
    sys.stdout.flush()


def config_mode():
    PHONES_DIR.mkdir(parents=True, exist_ok=True)

    config_files = sorted(PHONES_DIR.glob("*.yaml"))
    if not config_files:
        print("No phone configs found. Run 'backup_phone' with a phone connected first.")
        return

    connected_phones = detect_phones()
    connected_ids = {p["phone_id"] for p in connected_phones}

    import yaml as _yaml
    entries = []
    for cf in config_files:
        with open(cf) as f:
            cfg = _yaml.safe_load(f)
        phone_id = cfg.get("phone_id", cf.stem)
        name = cfg.get("phone_name", phone_id)
        n_sync = len(cfg.get("sync") or [])
        n_move = len(cfg.get("move") or [])
        n_undecided = len(cfg.get("undecided") or [])
        connected = phone_id in connected_ids
        entries.append((cf, phone_id, name, n_sync, n_move, n_undecided, connected))

    total_lines = 3 + len(entries) * 3 + 3
    sys.stdout.write("\n" * total_lines)

    selected = 0
    _render_menu(entries, selected)

    while True:
        key = _read_key()
        if key == "quit" or key == "esc":
            print()
            return
        elif key == "up":
            selected = (selected - 1) % len(entries)
        elif key == "down":
            selected = (selected + 1) % len(entries)
        elif key == "enter":
            break
        elif key.isdigit():
            num = int(key) - 1
            if 0 <= num < len(entries):
                selected = num
                break
        _render_menu(entries, selected)

    selected_config = entries[selected][0]
    print(f"\n  Opening {selected_config.name} in editor...\n")
    open_in_editor(selected_config)
    print("  Done. Run 'backup_phone' to use the updated config.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def ensure_phones_dir():
    """Make sure phones/ exists and has submodule content if configured."""
    script_dir = Path(__file__).parent
    phones_dir = script_dir / "phones"
    gitmodules = script_dir / ".gitmodules"

    if phones_dir.exists() and any(phones_dir.glob("*.yaml")):
        return  # Already populated

    # Try to initialize the submodule
    if gitmodules.exists() and (script_dir / ".git").exists():
        print("Initializing phones/ submodule...")
        result = subprocess.run(
            ["git", "submodule", "update", "--init", "phones"],
            cwd=script_dir,
            capture_output=True, text=True,
        )
        if result.returncode == 0 and any(phones_dir.glob("*.yaml")):
            print("Submodule initialized successfully.")
            return
        else:
            print("Could not fetch submodule (you may not have access to the private repo).")

    # Fallback: just create the directory
    phones_dir.mkdir(parents=True, exist_ok=True)
    print(f"Created empty {phones_dir}/ directory. Connect a phone to generate configs.")


def main():
    BACKUP_BASE.mkdir(parents=True, exist_ok=True)
    ensure_phones_dir()

    if len(sys.argv) > 1 and sys.argv[1] == "config":
        config_mode()
        return

    while True:
        result = curses.wrapper(backup_ui)
        if result and result[0] == "edit":
            open_in_editor(result[1])
        else:
            break


if __name__ == "__main__":
    main()
