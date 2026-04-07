"""Phone Backup TUI Application."""
import os
import time
from pathlib import Path
from datetime import datetime

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Button,
    Checkbox,
    Footer,
    Header,
    Label,
    ProgressBar,
    Static,
    TabbedContent,
    TabPane,
)

from detector import detect_phones
from config_manager import (
    create_phone_config,
    load_phone_config,
)
from transfer import (
    TransferStats,
    transfer_folder,
)


# --- USER-CONFIGURABLE PARAMETERS -------------------------------------------
BACKUP_BASE = Path.home() / "backup"
PHONES_DIR = Path(__file__).parent / "phones"
# -----------------------------------------------------------------------------


def format_size(size_bytes: float) -> str:
    """Format bytes to human-readable string."""
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def format_eta(seconds: float) -> str:
    """Format seconds to mm:ss or hh:mm:ss."""
    if seconds <= 0:
        return "--:--"
    seconds = int(seconds)
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60:02d}s"
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    return f"{hours}h {minutes:02d}m"


def folder_stats(folder_path: Path) -> tuple[int, int]:
    """Count files and total size in a folder. Returns (file_count, total_bytes)."""
    count = 0
    total = 0
    if not folder_path.exists():
        return 0, 0
    try:
        for f in folder_path.rglob("*"):
            if f.is_file() and not f.name.startswith(".tmp_"):
                count += 1
                try:
                    total += f.stat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    return count, total


class FolderCheckbox(Horizontal):
    """A checkbox with folder info."""

    DEFAULT_CSS = """
    FolderCheckbox {
        height: 3;
        padding: 0 1;
    }
    FolderCheckbox Checkbox {
        width: 1fr;
    }
    FolderCheckbox .folder-stats {
        width: 24;
        text-align: right;
        color: $text-muted;
    }
    """

    def __init__(self, source: str, dest: str, mount_path: Path, **kwargs):
        super().__init__(**kwargs)
        self.source = source
        self.dest = dest
        self.mount_path = mount_path
        self.full_source = mount_path / source

    def compose(self) -> ComposeResult:
        count, size = folder_stats(self.full_source)
        cb_id = f"cb_{abs(hash(self.source))}"
        yield Checkbox(self.source, value=True, id=cb_id)
        yield Label(
            f"{count} files, {format_size(size)}",
            classes="folder-stats",
        )

    @property
    def checked(self) -> bool:
        cb = self.query_one(Checkbox)
        return cb.value

    def set_checked(self, value: bool) -> None:
        cb = self.query_one(Checkbox)
        cb.value = value


class PhoneBackupApp(App):
    """Main TUI application."""

    TITLE = "Phone Backup"
    CSS = """
    Screen {
        layout: vertical;
    }
    #phone-info {
        height: 3;
        padding: 1 2;
        background: $primary;
        color: $text;
        text-style: bold;
    }
    #warning-banner {
        height: 3;
        padding: 1 2;
        background: $warning;
        color: $text;
        display: none;
    }
    #warning-banner.visible {
        display: block;
    }
    #select-all-sync, #select-all-move {
        margin: 1 2;
    }
    .folder-list {
        height: 1fr;
    }
    #progress-section {
        height: auto;
        max-height: 12;
        padding: 1 2;
        border-top: solid $primary;
    }
    #overall-label {
        margin-bottom: 1;
    }
    #current-file-label {
        margin-top: 1;
        color: $text-muted;
    }
    #button-bar {
        height: 5;
        padding: 1 2;
        align: center middle;
    }
    #button-bar Button {
        margin: 0 2;
    }
    #log-output {
        height: 6;
        padding: 0 2;
        color: $text-muted;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self):
        super().__init__()
        self.phone = None
        self.config = None
        self.transferring = False
        self.cancel_requested = False

    def compose(self) -> ComposeResult:
        yield Header()
        yield Label("Detecting phone...", id="phone-info")
        yield Label("", id="warning-banner")

        with TabbedContent():
            with TabPane("Sync (keep on phone)", id="sync-tab"):
                yield Checkbox("Select All", value=True, id="select-all-sync")
                yield VerticalScroll(id="sync-list", classes="folder-list")
            with TabPane("Move (delete from phone)", id="move-tab"):
                yield Checkbox("Select All", value=True, id="select-all-move")
                yield VerticalScroll(id="move-list", classes="folder-list")

        with Vertical(id="progress-section"):
            yield Label("Ready", id="overall-label")
            yield ProgressBar(total=100, show_eta=False, id="overall-progress")
            yield Label("", id="current-file-label")
            yield Static("", id="log-output")

        with Horizontal(id="button-bar"):
            yield Button("Start Backup", id="start-btn", variant="success")
            yield Button("Refresh", id="refresh-btn")
            yield Button("Quit", id="quit-btn", variant="error")

        yield Footer()

    def on_mount(self) -> None:
        self.detect_and_load()

    def detect_and_load(self) -> None:
        """Detect phone and load/create config."""
        phones = detect_phones()
        info_label = self.query_one("#phone-info", Label)

        if not phones:
            info_label.update(
                "No phone detected. Connect a phone in file transfer mode and press Refresh."
            )
            return

        self.phone = phones[0]
        phone_id = self.phone["phone_id"]
        display = self.phone["display_name"]
        info_label.update(f"Connected: {display} ({phone_id})")

        PHONES_DIR.mkdir(parents=True, exist_ok=True)
        self.config = load_phone_config(phone_id, PHONES_DIR)
        if self.config is None:
            self.config = create_phone_config(
                phone_id=phone_id,
                display_name=display,
                mount_path=self.phone["mount_path"],
                phones_dir=PHONES_DIR,
                backup_base=BACKUP_BASE,
            )

        self.populate_folders()

    def populate_folders(self) -> None:
        """Fill the sync and move tab lists with checkboxes."""
        if not self.config or not self.phone:
            return

        mount_path = self.phone["mount_path"]

        undecided = self.config.get("undecided", [])
        warning = self.query_one("#warning-banner", Label)
        if undecided:
            config_path = PHONES_DIR / (self.config["phone_id"] + ".yaml")
            warning.update(
                f"  {len(undecided)} folders in 'undecided'. "
                f"Edit {config_path} to categorize them."
            )
            warning.add_class("visible")
        else:
            warning.remove_class("visible")

        sync_list = self.query_one("#sync-list", VerticalScroll)
        sync_list.remove_children()
        for entry in self.config.get("sync", []):
            sync_list.mount(
                FolderCheckbox(
                    source=entry["source"],
                    dest=entry["dest"],
                    mount_path=mount_path,
                )
            )

        move_list = self.query_one("#move-list", VerticalScroll)
        move_list.remove_children()
        for entry in self.config.get("move", []):
            move_list.mount(
                FolderCheckbox(
                    source=entry["source"],
                    dest=entry["dest"],
                    mount_path=mount_path,
                )
            )

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        """Handle select/deselect all."""
        if event.checkbox.id == "select-all-sync":
            for fc in self.query_one("#sync-list").query(FolderCheckbox):
                fc.set_checked(event.value)
        elif event.checkbox.id == "select-all-move":
            for fc in self.query_one("#move-list").query(FolderCheckbox):
                fc.set_checked(event.value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "start-btn":
            if not self.transferring:
                self.start_backup()
        elif event.button.id == "refresh-btn":
            self.detect_and_load()
        elif event.button.id == "quit-btn":
            if self.transferring:
                self.cancel_requested = True
            else:
                self.exit()

    @work(thread=True)
    def start_backup(self) -> None:
        """Run the backup in a background thread."""
        if not self.phone or not self.config:
            return

        self.transferring = True
        self.cancel_requested = False
        mount_path = self.phone["mount_path"]
        backup_root = Path(self.config["backup_root"])
        backup_root.mkdir(parents=True, exist_ok=True)

        tasks = []

        for fc in self.query_one("#sync-list").query(FolderCheckbox):
            if fc.checked:
                tasks.append((
                    mount_path / fc.source,
                    backup_root / fc.dest,
                    False,
                ))

        for fc in self.query_one("#move-list").query(FolderCheckbox):
            if fc.checked:
                tasks.append((
                    mount_path / fc.source,
                    backup_root / fc.dest,
                    True,
                ))

        if not tasks:
            self.call_from_thread(self.update_overall, "No folders selected.")
            self.transferring = False
            return

        total_files = 0
        total_bytes = 0
        self.call_from_thread(self.update_overall, "Scanning folders...")

        for src, dst, _ in tasks:
            if not src.exists():
                continue
            for f in src.rglob("*"):
                if f.is_file() and not f.name.startswith(".tmp_"):
                    total_files += 1
                    try:
                        total_bytes += f.stat().st_size
                    except OSError:
                        pass

        stats = TransferStats(total_files=total_files, total_bytes=total_bytes)

        log_path = PHONES_DIR / f"{self.config['phone_id']}.transfer.log"
        log_file = open(log_path, "a")
        log_file.write(f"\n--- Transfer started {datetime.now().isoformat()} ---\n")

        def on_progress():
            pct = stats.percent_bytes
            eta = format_eta(stats.eta_seconds)
            done = stats.files_done + stats.files_skipped
            self.call_from_thread(
                self.update_progress,
                pct,
                f"Overall: {done} / {stats.total_files} files "
                f"({format_size(stats.bytes_done)} / {format_size(stats.total_bytes)}) "
                f"ETA: {eta}",
                f"Current: {stats.current_file} "
                f"({format_size(stats.current_file_copied)} / "
                f"{format_size(stats.current_file_bytes)})",
            )

        def on_log(msg):
            timestamp = datetime.now().strftime("%H:%M:%S")
            line = f"[{timestamp}] {msg}"
            log_file.write(line + "\n")
            log_file.flush()
            self.call_from_thread(self.update_log, line)

        for src, dst, delete in tasks:
            if self.cancel_requested:
                on_log("CANCELLED by user")
                break
            on_log(f"START {'MOVE' if delete else 'SYNC'} {src.name} -> {dst}")
            transfer_folder(
                src_folder=src,
                dst_folder=dst,
                stats=stats,
                delete_source=delete,
                progress_callback=on_progress,
                log_callback=on_log,
            )

        log_file.write(f"--- Transfer finished {datetime.now().isoformat()} ---\n")
        log_file.close()

        summary = (
            f"Done. {stats.files_done} copied, {stats.files_skipped} skipped, "
            f"{stats.files_failed} failed."
        )
        self.call_from_thread(self.update_overall, summary)
        self.call_from_thread(self.update_progress, 100.0, summary, "")
        self.transferring = False

    def update_progress(self, percent: float, overall_text: str, file_text: str) -> None:
        self.query_one("#overall-progress", ProgressBar).update(progress=percent)
        self.query_one("#overall-label", Label).update(overall_text)
        self.query_one("#current-file-label", Label).update(file_text)

    def update_overall(self, text: str) -> None:
        self.query_one("#overall-label", Label).update(text)

    def update_log(self, line: str) -> None:
        log_widget = self.query_one("#log-output", Static)
        current = str(log_widget.renderable)
        lines = current.split("\n") if current else []
        lines.append(line)
        lines = lines[-20:]
        log_widget.update("\n".join(lines))


def main():
    BACKUP_BASE.mkdir(parents=True, exist_ok=True)
    PHONES_DIR.mkdir(parents=True, exist_ok=True)
    app = PhoneBackupApp()
    app.run()


if __name__ == "__main__":
    main()
