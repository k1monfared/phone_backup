# Phone Backup TUI Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build an interactive TUI that detects MTP-connected phones, manages per-phone YAML configs with sync/move/undecided folder lists, and performs safe file transfers with progress tracking.

**Architecture:** Four modules in a single-directory layout: detector (GVFS scanning), config manager (YAML read/write with mapping heuristics), transfer engine (safe copy with temp files), and TUI app (Textual with tabs/checkboxes/progress). Entry point is `phone_backup.py`.

**Tech Stack:** Python 3.12, Textual, PyYAML, pathlib, shutil

---

### Task 1: Project Setup

**Files:**
- Create: `requirements.txt`
- Create: `phones/.gitkeep`

**Step 1: Create requirements.txt**

```
textual>=0.40.0
pyyaml>=6.0
```

**Step 2: Create phones directory**

```bash
mkdir -p phones && touch phones/.gitkeep
```

**Step 3: Install dependencies**

```bash
pip install -r requirements.txt
```

**Step 4: Update .gitignore**

Add to existing `.gitignore`:
```
phones/*.transfer.log
__pycache__/
*.pyc
```

**Step 5: Commit**

```bash
git add requirements.txt phones/.gitkeep .gitignore
git commit -m "feat: project setup with dependencies"
```

---

### Task 2: Phone Detector Module

**Files:**
- Create: `detector.py`
- Create: `tests/test_detector.py`

**Step 1: Write the failing test**

```python
# tests/test_detector.py
import os
import tempfile
from pathlib import Path
from detector import detect_phones, get_gvfs_base


def test_detect_phones_finds_mtp_mounts(tmp_path):
    """Simulate GVFS directory with MTP mounts."""
    mtp_dir = tmp_path / "mtp:host=motorola_moto_g85_5G_ZY22KH9KPW"
    mtp_dir.mkdir()
    (mtp_dir / "Internal shared storage").mkdir()

    phones = detect_phones(gvfs_path=tmp_path)
    assert len(phones) == 1
    assert phones[0]["phone_id"] == "motorola_moto_g85_5G_ZY22KH9KPW"
    assert phones[0]["mount_path"] == mtp_dir


def test_detect_phones_ignores_non_mtp(tmp_path):
    """Non-MTP mounts should be ignored."""
    (tmp_path / "gphoto2:host=some_camera").mkdir()
    (tmp_path / "smb-share:server=nas").mkdir()

    phones = detect_phones(gvfs_path=tmp_path)
    assert len(phones) == 0


def test_detect_phones_multiple(tmp_path):
    """Multiple phones detected."""
    (tmp_path / "mtp:host=phone_A").mkdir()
    (tmp_path / "mtp:host=phone_B").mkdir()

    phones = detect_phones(gvfs_path=tmp_path)
    assert len(phones) == 2
    ids = {p["phone_id"] for p in phones}
    assert ids == {"phone_A", "phone_B"}


def test_detect_phones_extracts_display_name():
    """Phone ID like motorola_moto_g85_5G_ZY22KH9KPW becomes readable name."""
    from detector import phone_display_name
    assert phone_display_name("motorola_moto_g85_5G_ZY22KH9KPW") == "Motorola Moto G85 5G"


def test_get_storage_roots(tmp_path):
    """List storage roots (Internal shared storage, SD card, etc.)."""
    from detector import get_storage_roots
    mount = tmp_path / "mtp:host=phone_A"
    mount.mkdir()
    (mount / "Internal shared storage").mkdir()
    (mount / "SD card").mkdir()

    roots = get_storage_roots(mount)
    assert set(roots) == {"Internal shared storage", "SD card"}
```

**Step 2: Run test to verify it fails**

```bash
cd /home/k1/public/phone_backup && python -m pytest tests/test_detector.py -v
```
Expected: FAIL (module not found)

**Step 3: Write implementation**

```python
# detector.py
"""Detect MTP-connected Android phones via GVFS."""
import os
from pathlib import Path


def get_gvfs_base() -> Path:
    """Return the GVFS mount base directory for the current user."""
    uid = os.getuid()
    return Path(f"/run/user/{uid}/gvfs")


def detect_phones(gvfs_path: Path = None) -> list[dict]:
    """
    Scan GVFS directory for MTP phone mounts.

    Returns list of dicts with keys: phone_id, mount_path, display_name
    """
    if gvfs_path is None:
        gvfs_path = get_gvfs_base()

    if not gvfs_path.exists():
        return []

    phones = []
    for entry in sorted(gvfs_path.iterdir()):
        if entry.is_dir() and entry.name.startswith("mtp:host="):
            phone_id = entry.name.removeprefix("mtp:host=")
            phones.append({
                "phone_id": phone_id,
                "mount_path": entry,
                "display_name": phone_display_name(phone_id),
            })
    return phones


def phone_display_name(phone_id: str) -> str:
    """
    Convert phone_id to a readable name.
    motorola_moto_g85_5G_ZY22KH9KPW -> Motorola Moto G85 5G
    Strips the serial number (last segment if it looks like a serial).
    """
    parts = phone_id.split("_")
    # Serial numbers are typically uppercase alphanumeric, 8+ chars
    # Remove trailing serial-looking parts
    while parts and len(parts[-1]) >= 8 and parts[-1].isalnum() and parts[-1].isupper():
        parts.pop()
    if not parts:
        return phone_id
    # Title-case each part, but keep things like "5G" uppercase
    result = []
    for p in parts:
        if p.isupper() and len(p) <= 3:
            result.append(p)
        else:
            result.append(p.title())
    return " ".join(result)


def get_storage_roots(mount_path: Path) -> list[str]:
    """List storage roots on a mounted phone (Internal shared storage, SD card, etc.)."""
    if not mount_path.exists():
        return []
    return sorted(
        entry.name for entry in mount_path.iterdir()
        if entry.is_dir() and not entry.name.startswith(".")
    )
```

**Step 4: Run tests**

```bash
python -m pytest tests/test_detector.py -v
```
Expected: all PASS

**Step 5: Commit**

```bash
git add detector.py tests/test_detector.py
git commit -m "feat: phone detector module with GVFS MTP scanning"
```

---

### Task 3: Config Manager Module

**Files:**
- Create: `config_manager.py`
- Create: `tests/test_config_manager.py`

**Step 1: Write failing tests**

```python
# tests/test_config_manager.py
import yaml
from pathlib import Path
from config_manager import (
    create_phone_config,
    load_phone_config,
    save_phone_config,
    guess_dest_mapping,
    scan_phone_folders,
)


def test_guess_dest_mapping_camera():
    assert guess_dest_mapping("Internal shared storage/DCIM/Camera") == "photos/camera"


def test_guess_dest_mapping_screenshots():
    assert guess_dest_mapping("Internal shared storage/Pictures/Screenshots") == "photos/screenshots"


def test_guess_dest_mapping_whatsapp_images():
    assert guess_dest_mapping("Internal shared storage/WhatsApp/Media/WhatsApp Images") == "photos/messaging"


def test_guess_dest_mapping_whatsapp_video():
    assert guess_dest_mapping("Internal shared storage/WhatsApp/Media/WhatsApp Video") == "videos/messaging"


def test_guess_dest_mapping_whatsapp_audio():
    assert guess_dest_mapping("Internal shared storage/WhatsApp/Media/WhatsApp Audio") == "audio/messaging"


def test_guess_dest_mapping_music():
    assert guess_dest_mapping("Internal shared storage/Music") == "audio/music"


def test_guess_dest_mapping_movies():
    assert guess_dest_mapping("Internal shared storage/Movies") == "videos/personal"


def test_guess_dest_mapping_recordings():
    assert guess_dest_mapping("Internal shared storage/Recordings") == "audio/recordings"


def test_guess_dest_mapping_documents():
    assert guess_dest_mapping("Internal shared storage/Documents") == "documents"


def test_guess_dest_mapping_downloads():
    assert guess_dest_mapping("Internal shared storage/Download") == "downloads"


def test_guess_dest_mapping_unknown():
    assert guess_dest_mapping("Internal shared storage/SomeApp") == "other/SomeApp"


def test_guess_dest_mapping_telegram_images():
    assert guess_dest_mapping("Internal shared storage/Telegram/Telegram Images") == "photos/messaging"


def test_guess_dest_mapping_telegram_video():
    assert guess_dest_mapping("Internal shared storage/Telegram/Telegram Video") == "videos/messaging"


def test_scan_phone_folders(tmp_path):
    """Scan phone mount and return all non-hidden folders recursively (first two levels)."""
    storage = tmp_path / "Internal shared storage"
    storage.mkdir()
    (storage / "DCIM" / "Camera").mkdir(parents=True)
    (storage / "DCIM" / ".thumbnails").mkdir(parents=True)
    (storage / "Music").mkdir()
    (storage / "Android" / "data").mkdir(parents=True)

    folders = scan_phone_folders(tmp_path)
    folder_strs = [str(f) for f in folders]
    assert "Internal shared storage/DCIM/Camera" in folder_strs
    assert "Internal shared storage/Music" in folder_strs
    # Hidden folders excluded
    assert "Internal shared storage/DCIM/.thumbnails" not in folder_strs
    # Android/data excluded (system folder)
    assert "Internal shared storage/Android/data" not in folder_strs


def test_create_phone_config(tmp_path):
    """Create a new config file for a detected phone."""
    mount = tmp_path / "phone_mount"
    storage = mount / "Internal shared storage"
    (storage / "DCIM" / "Camera").mkdir(parents=True)
    (storage / "Music").mkdir(parents=True)

    phones_dir = tmp_path / "phones"
    phones_dir.mkdir()

    config = create_phone_config(
        phone_id="test_phone_ABC123",
        display_name="Test Phone",
        mount_path=mount,
        phones_dir=phones_dir,
        backup_base=Path("/home/user/backup"),
    )

    config_file = phones_dir / "test_phone_ABC123.yaml"
    assert config_file.exists()

    loaded = yaml.safe_load(config_file.read_text())
    assert loaded["phone_id"] == "test_phone_ABC123"
    assert loaded["phone_name"] == "Test Phone"
    assert loaded["backup_root"] == "/home/user/backup/test_phone_ABC123"
    assert loaded["sync"] == []
    assert loaded["move"] == []
    assert len(loaded["undecided"]) == 2  # DCIM/Camera and Music


def test_load_phone_config(tmp_path):
    """Load an existing config."""
    phones_dir = tmp_path / "phones"
    phones_dir.mkdir()
    config_file = phones_dir / "test_phone.yaml"
    config_file.write_text(yaml.dump({
        "phone_id": "test_phone",
        "phone_name": "Test",
        "backup_root": "/backup/test_phone",
        "sync": [{"source": "Internal shared storage/Music", "dest": "audio/music"}],
        "move": [],
        "undecided": [],
    }))

    config = load_phone_config("test_phone", phones_dir)
    assert config["phone_name"] == "Test"
    assert len(config["sync"]) == 1
    assert config["sync"][0]["source"] == "Internal shared storage/Music"
```

**Step 2: Run tests to verify failure**

```bash
python -m pytest tests/test_config_manager.py -v
```
Expected: FAIL

**Step 3: Write implementation**

```python
# config_manager.py
"""Manage per-phone YAML configuration files."""
import yaml
from pathlib import Path

# Folders to skip during phone scanning
SKIP_FOLDERS = {"Android", ".thumbnails", ".trash"}

# Mapping rules: (path_contains, dest_prefix)
# Order matters: first match wins
DEST_MAPPING_RULES = [
    ("DCIM/Camera", "photos/camera"),
    ("DCIM", "photos/camera"),
    ("Pictures/Screenshots", "photos/screenshots"),
    ("Pictures", "photos/other"),
    ("WhatsApp/Media/WhatsApp Images", "photos/messaging"),
    ("WhatsApp/Media/WhatsApp Video", "videos/messaging"),
    ("WhatsApp/Media/WhatsApp Audio", "audio/messaging"),
    ("WhatsApp/Media/WhatsApp Animated Gifs", "photos/messaging"),
    ("WhatsApp/Media/WhatsApp Documents", "documents/messaging"),
    ("WhatsApp/Media/WhatsApp Voice Notes", "audio/messaging"),
    ("WhatsApp/Media", "other/whatsapp"),
    ("Telegram/Telegram Images", "photos/messaging"),
    ("Telegram/Telegram Video", "videos/messaging"),
    ("Telegram/Telegram Audio", "audio/messaging"),
    ("Telegram/Telegram Documents", "documents/messaging"),
    ("Telegram", "other/telegram"),
    ("Movies", "videos/personal"),
    ("Music", "audio/music"),
    ("Recordings", "audio/recordings"),
    ("Ringtones", "audio/ringtones"),
    ("Notifications", "audio/notifications"),
    ("Alarms", "audio/alarms"),
    ("Podcasts", "audio/podcasts"),
    ("Audiobooks", "audio/audiobooks"),
    ("Documents", "documents"),
    ("Download", "downloads"),
    ("Books", "books"),
]


def guess_dest_mapping(source_path: str) -> str:
    """
    Given a source path relative to the phone mount, guess the destination mapping.
    Returns a destination path relative to backup_root.
    """
    for pattern, dest in DEST_MAPPING_RULES:
        if pattern in source_path:
            return dest
    # Fallback: use last folder name
    folder_name = Path(source_path).name
    return f"other/{folder_name}"


def scan_phone_folders(mount_path: Path) -> list[Path]:
    """
    Scan phone mount for backup-worthy folders.
    Returns relative paths (from mount_path) for folders two levels deep
    under each storage root, excluding system/hidden folders.
    """
    folders = []
    if not mount_path.exists():
        return folders

    for storage_root in sorted(mount_path.iterdir()):
        if not storage_root.is_dir() or storage_root.name.startswith("."):
            continue
        # First level under storage root
        for level1 in sorted(storage_root.iterdir()):
            if not level1.is_dir() or level1.name.startswith("."):
                continue
            if level1.name in SKIP_FOLDERS:
                continue
            # Check for meaningful subfolders
            has_subfolders = False
            for level2 in sorted(level1.iterdir()):
                if not level2.is_dir() or level2.name.startswith("."):
                    continue
                if level2.name in SKIP_FOLDERS:
                    continue
                folders.append(level2.relative_to(mount_path))
                has_subfolders = True
            # If no subfolders, include the level1 folder itself
            if not has_subfolders:
                folders.append(level1.relative_to(mount_path))

    return folders


def create_phone_config(
    phone_id: str,
    display_name: str,
    mount_path: Path,
    phones_dir: Path,
    backup_base: Path,
) -> dict:
    """
    Create a new YAML config for a detected phone.
    All folders go to 'undecided' for user to sort.
    """
    folders = scan_phone_folders(mount_path)

    undecided = []
    for folder in folders:
        source = str(folder)
        dest = guess_dest_mapping(source)
        undecided.append({"source": source, "dest": dest})

    config = {
        "phone_id": phone_id,
        "phone_name": display_name,
        "backup_root": str(backup_base / phone_id),
        "sync": [],
        "move": [],
        "undecided": undecided,
    }

    config_file = phones_dir / f"{phone_id}.yaml"
    save_phone_config(config, phones_dir)

    return config


def load_phone_config(phone_id: str, phones_dir: Path) -> dict:
    """Load a phone config from YAML file."""
    config_file = phones_dir / f"{phone_id}.yaml"
    if not config_file.exists():
        return None
    with open(config_file) as f:
        return yaml.safe_load(f)


def save_phone_config(config: dict, phones_dir: Path) -> None:
    """Save a phone config to YAML file."""
    phones_dir.mkdir(parents=True, exist_ok=True)
    config_file = phones_dir / f"{config['phone_id']}.yaml"
    with open(config_file, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
```

**Step 4: Run tests**

```bash
python -m pytest tests/test_config_manager.py -v
```
Expected: all PASS

**Step 5: Commit**

```bash
git add config_manager.py tests/test_config_manager.py
git commit -m "feat: config manager with YAML configs and dest mapping heuristics"
```

---

### Task 4: Transfer Engine Module

**Files:**
- Create: `transfer.py`
- Create: `tests/test_transfer.py`

**Step 1: Write failing tests**

```python
# tests/test_transfer.py
import os
from pathlib import Path
from transfer import (
    enumerate_files,
    safe_copy_file,
    should_skip_file,
    clean_tmp_files,
    TransferStats,
)


def test_enumerate_files(tmp_path):
    """List all files in a directory recursively."""
    (tmp_path / "a.jpg").write_bytes(b"x" * 100)
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.png").write_bytes(b"y" * 200)
    (tmp_path / ".tmp_partial").write_bytes(b"z" * 50)

    files = enumerate_files(tmp_path)
    names = {f.name for f in files}
    assert names == {"a.jpg", "b.png"}
    # .tmp_ files excluded from enumeration
    assert ".tmp_partial" not in names


def test_should_skip_file_already_exists(tmp_path):
    """Skip if dest has same name and same size."""
    src = tmp_path / "src"
    src.mkdir()
    dst = tmp_path / "dst"
    dst.mkdir()

    (src / "photo.jpg").write_bytes(b"x" * 100)
    (dst / "photo.jpg").write_bytes(b"x" * 100)

    assert should_skip_file(src / "photo.jpg", dst / "photo.jpg") is True


def test_should_not_skip_different_size(tmp_path):
    """Don't skip if sizes differ."""
    src = tmp_path / "src"
    src.mkdir()
    dst = tmp_path / "dst"
    dst.mkdir()

    (src / "photo.jpg").write_bytes(b"x" * 100)
    (dst / "photo.jpg").write_bytes(b"x" * 50)

    assert should_skip_file(src / "photo.jpg", dst / "photo.jpg") is False


def test_should_not_skip_missing(tmp_path):
    """Don't skip if dest doesn't exist."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "photo.jpg").write_bytes(b"x" * 100)

    assert should_skip_file(src / "photo.jpg", tmp_path / "dst" / "photo.jpg") is False


def test_safe_copy_file(tmp_path):
    """Copy file via temp, verify size, rename to final."""
    src = tmp_path / "src"
    src.mkdir()
    dst = tmp_path / "dst"
    dst.mkdir()

    content = b"hello world" * 1000
    (src / "test.txt").write_bytes(content)

    result = safe_copy_file(src / "test.txt", dst / "test.txt")
    assert result is True
    assert (dst / "test.txt").exists()
    assert (dst / "test.txt").read_bytes() == content
    # No temp files left behind
    assert not list(dst.glob(".tmp_*"))


def test_safe_copy_file_creates_parent_dirs(tmp_path):
    """Dest parent directories created automatically."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "file.txt").write_bytes(b"data")

    dest_file = tmp_path / "dst" / "deep" / "nested" / "file.txt"
    result = safe_copy_file(src / "file.txt", dest_file)
    assert result is True
    assert dest_file.exists()


def test_clean_tmp_files(tmp_path):
    """Remove leftover .tmp_ files from previous interrupted runs."""
    (tmp_path / ".tmp_photo.jpg").write_bytes(b"partial")
    (tmp_path / "real_file.txt").write_bytes(b"keep")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / ".tmp_video.mp4").write_bytes(b"partial2")

    removed = clean_tmp_files(tmp_path)
    assert removed == 2
    assert not (tmp_path / ".tmp_photo.jpg").exists()
    assert not (tmp_path / "sub" / ".tmp_video.mp4").exists()
    assert (tmp_path / "real_file.txt").exists()


def test_transfer_stats():
    """TransferStats tracks progress."""
    stats = TransferStats(total_files=10, total_bytes=1000)
    assert stats.percent_files == 0.0

    stats.file_done(100)
    assert stats.files_done == 1
    assert stats.bytes_done == 100
    assert stats.percent_files == 10.0
```

**Step 2: Run tests**

```bash
python -m pytest tests/test_transfer.py -v
```
Expected: FAIL

**Step 3: Write implementation**

```python
# transfer.py
"""Safe file transfer engine with progress tracking."""
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


@dataclass
class TransferStats:
    """Track transfer progress."""
    total_files: int = 0
    total_bytes: int = 0
    files_done: int = 0
    bytes_done: int = 0
    files_skipped: int = 0
    files_failed: int = 0
    current_file: str = ""
    current_file_bytes: int = 0
    current_file_copied: int = 0
    start_time: float = field(default_factory=time.time)

    @property
    def percent_files(self) -> float:
        if self.total_files == 0:
            return 0.0
        return (self.files_done / self.total_files) * 100

    @property
    def percent_bytes(self) -> float:
        if self.total_bytes == 0:
            return 0.0
        return (self.bytes_done / self.total_bytes) * 100

    @property
    def eta_seconds(self) -> float:
        elapsed = time.time() - self.start_time
        if self.bytes_done == 0 or elapsed == 0:
            return 0.0
        rate = self.bytes_done / elapsed
        remaining = self.total_bytes - self.bytes_done
        return remaining / rate

    def file_done(self, file_bytes: int) -> None:
        self.files_done += 1
        self.bytes_done += file_bytes


def enumerate_files(folder: Path) -> list[Path]:
    """
    Recursively list all files in folder, excluding .tmp_ prefixed files.
    Returns list of Path objects.
    """
    files = []
    if not folder.exists():
        return files
    for item in sorted(folder.rglob("*")):
        if item.is_file() and not item.name.startswith(".tmp_"):
            files.append(item)
    return files


def should_skip_file(src: Path, dst: Path) -> bool:
    """Check if file already exists at destination with same size."""
    if not dst.exists():
        return False
    return src.stat().st_size == dst.stat().st_size


def safe_copy_file(
    src: Path,
    dst: Path,
    progress_callback: Callable[[int], None] = None,
    chunk_size: int = 1024 * 1024,
) -> bool:
    """
    Safely copy a file: write to .tmp_ first, verify size, then rename.
    Returns True on success, False on failure.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp_dst = dst.parent / f".tmp_{dst.name}"

    try:
        src_size = src.stat().st_size
        copied = 0

        with open(src, "rb") as fsrc, open(tmp_dst, "wb") as fdst:
            while True:
                chunk = fsrc.read(chunk_size)
                if not chunk:
                    break
                fdst.write(chunk)
                copied += len(chunk)
                if progress_callback:
                    progress_callback(len(chunk))

        # Verify size
        tmp_size = tmp_dst.stat().st_size
        if tmp_size != src_size:
            tmp_dst.unlink(missing_ok=True)
            return False

        # Atomic rename
        tmp_dst.rename(dst)
        return True
    except (OSError, IOError):
        tmp_dst.unlink(missing_ok=True)
        return False


def clean_tmp_files(folder: Path) -> int:
    """Remove leftover .tmp_ files from interrupted transfers. Returns count removed."""
    count = 0
    if not folder.exists():
        return count
    for tmp_file in folder.rglob(".tmp_*"):
        if tmp_file.is_file():
            tmp_file.unlink()
            count += 1
    return count


def transfer_folder(
    src_folder: Path,
    dst_folder: Path,
    stats: TransferStats,
    delete_source: bool = False,
    progress_callback: Callable[[], None] = None,
    log_callback: Callable[[str], None] = None,
) -> None:
    """
    Transfer all files from src_folder to dst_folder.
    If delete_source is True, remove source files after verified copy (move mode).
    Preserves subfolder structure relative to src_folder.
    """
    # Clean up any leftover temp files from previous runs
    clean_tmp_files(dst_folder)

    files = enumerate_files(src_folder)

    for src_file in files:
        rel_path = src_file.relative_to(src_folder)
        dst_file = dst_folder / rel_path

        stats.current_file = src_file.name
        stats.current_file_bytes = src_file.stat().st_size
        stats.current_file_copied = 0

        if should_skip_file(src_file, dst_file):
            stats.files_skipped += 1
            stats.file_done(src_file.stat().st_size)
            if log_callback:
                log_callback(f"SKIP {rel_path}")
            if progress_callback:
                progress_callback()
            continue

        def on_chunk(chunk_bytes):
            stats.current_file_copied += chunk_bytes
            if progress_callback:
                progress_callback()

        success = safe_copy_file(src_file, dst_file, progress_callback=on_chunk)

        if success:
            stats.file_done(src_file.stat().st_size)
            if log_callback:
                log_callback(f"{'MOVE' if delete_source else 'COPY'} {rel_path}")
            if delete_source:
                try:
                    src_file.unlink()
                    if log_callback:
                        log_callback(f"DELETE {rel_path}")
                except OSError:
                    if log_callback:
                        log_callback(f"DELETE_FAILED {rel_path}")
        else:
            stats.files_failed += 1
            if log_callback:
                log_callback(f"FAILED {rel_path}")

        if progress_callback:
            progress_callback()
```

**Step 4: Run tests**

```bash
python -m pytest tests/test_transfer.py -v
```
Expected: all PASS

**Step 5: Commit**

```bash
git add transfer.py tests/test_transfer.py
git commit -m "feat: safe transfer engine with temp files and progress tracking"
```

---

### Task 5: TUI Application

**Files:**
- Create: `phone_backup.py`

This is the main Textual app. Due to TUI complexity, this task is not TDD.
Manual testing against a connected phone.

**Step 1: Write the TUI app**

```python
# phone_backup.py
"""Phone Backup TUI Application."""
import asyncio
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

from detector import detect_phones, get_gvfs_base
from config_manager import (
    create_phone_config,
    load_phone_config,
    save_phone_config,
    scan_phone_folders,
)
from transfer import (
    TransferStats,
    enumerate_files,
    transfer_folder,
    clean_tmp_files,
)


# ─── USER-CONFIGURABLE PARAMETERS ─────────────────────────────────────────
BACKUP_BASE = Path.home() / "backup"
PHONES_DIR = Path(__file__).parent / "phones"
# ───────────────────────────────────────────────────────────────────────────


def format_size(size_bytes: int) -> str:
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
        width: 20;
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
        yield Checkbox(self.source, value=True, id=f"cb_{hash(self.source)}")
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
    .tab-content {
        height: 1fr;
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
        height: 3;
        padding: 0 2;
        align: center middle;
    }
    #button-bar Button {
        margin: 0 2;
    }
    #log-output {
        height: 4;
        padding: 0 2;
        color: $text-muted;
        overflow-y: auto;
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
            info_label.update("No phone detected. Connect a phone in file transfer mode and press Refresh.")
            return

        self.phone = phones[0]  # Use first detected phone
        phone_id = self.phone["phone_id"]
        display = self.phone["display_name"]
        info_label.update(f"Connected: {display} ({phone_id})")

        # Load or create config
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

        # Warning for undecided folders
        undecided = self.config.get("undecided", [])
        warning = self.query_one("#warning-banner", Label)
        if undecided:
            warning.update(
                f"  {len(undecided)} folders in 'undecided'. "
                f"Edit {PHONES_DIR / (self.config['phone_id'] + '.yaml')} to categorize them."
            )
            warning.add_class("visible")
        else:
            warning.remove_class("visible")

        # Populate sync tab
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

        # Populate move tab
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

        # Collect selected folders
        tasks = []  # (src_folder, dst_folder, delete_source)

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

        # Pre-scan for total counts
        total_files = 0
        total_bytes = 0
        self.call_from_thread(self.update_overall, "Scanning folders...")

        for src, dst, _ in tasks:
            for f in src.rglob("*") if src.exists() else []:
                if f.is_file() and not f.name.startswith(".tmp_"):
                    total_files += 1
                    try:
                        total_bytes += f.stat().st_size
                    except OSError:
                        pass

        stats = TransferStats(total_files=total_files, total_bytes=total_bytes)

        # Open log file
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
                f"({format_size(stats.current_file_copied)} / {format_size(stats.current_file_bytes)})",
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
        # Keep last 20 lines
        lines = lines[-20:]
        log_widget.update("\n".join(lines))


def main():
    BACKUP_BASE.mkdir(parents=True, exist_ok=True)
    PHONES_DIR.mkdir(parents=True, exist_ok=True)
    app = PhoneBackupApp()
    app.run()


if __name__ == "__main__":
    main()
```

**Step 2: Test manually**

```bash
cd /home/k1/public/phone_backup && python phone_backup.py
```

Verify:
- Phone detected and shown in header
- Config YAML created in phones/ directory
- Tabs show sync/move folders
- Select/deselect all works
- Warning banner shows undecided count
- Start backup copies files correctly
- Progress bar updates
- Cancel stops transfer

**Step 3: Commit**

```bash
git add phone_backup.py
git commit -m "feat: TUI application with tabs, checkboxes, and progress"
```

---

### Task 6: Create tests/__init__.py and Integration Test

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/test_integration.py`

**Step 1: Create test init**

Empty file to make tests a package:
```bash
touch tests/__init__.py
```

**Step 2: Write integration test**

```python
# tests/test_integration.py
"""Integration test: full flow from detection to config creation."""
import yaml
from pathlib import Path
from detector import detect_phones
from config_manager import create_phone_config, load_phone_config


def test_full_flow_new_phone(tmp_path):
    """Simulate detecting a new phone and creating its config."""
    # Set up fake GVFS mount
    gvfs = tmp_path / "gvfs"
    mount = gvfs / "mtp:host=samsung_galaxy_s24_R5ABC123"
    storage = mount / "Internal shared storage"
    (storage / "DCIM" / "Camera").mkdir(parents=True)
    (storage / "Music").mkdir(parents=True)
    (storage / "Download").mkdir(parents=True)
    (storage / "WhatsApp" / "Media" / "WhatsApp Images").mkdir(parents=True)
    # Add some test files
    (storage / "DCIM" / "Camera" / "IMG_001.jpg").write_bytes(b"x" * 1024)
    (storage / "DCIM" / "Camera" / "IMG_002.jpg").write_bytes(b"y" * 2048)
    (storage / "Music" / "song.mp3").write_bytes(b"z" * 512)

    # Detect
    phones = detect_phones(gvfs_path=gvfs)
    assert len(phones) == 1
    phone = phones[0]
    assert phone["phone_id"] == "samsung_galaxy_s24_R5ABC123"

    # Create config
    phones_dir = tmp_path / "phones"
    phones_dir.mkdir()
    config = create_phone_config(
        phone_id=phone["phone_id"],
        display_name=phone["display_name"],
        mount_path=phone["mount_path"],
        phones_dir=phones_dir,
        backup_base=tmp_path / "backup",
    )

    # Verify config
    assert config["phone_id"] == "samsung_galaxy_s24_R5ABC123"
    assert len(config["undecided"]) >= 3  # at least Camera, Music, Download
    assert config["sync"] == []
    assert config["move"] == []

    # Verify dest mappings
    dests = {e["source"]: e["dest"] for e in config["undecided"]}
    assert dests.get("Internal shared storage/DCIM/Camera") == "photos/camera"
    assert dests.get("Internal shared storage/Music") == "audio/music"
    assert dests.get("Internal shared storage/Download") == "downloads"

    # Reload from disk
    loaded = load_phone_config("samsung_galaxy_s24_R5ABC123", phones_dir)
    assert loaded == config
```

**Step 3: Run all tests**

```bash
python -m pytest tests/ -v
```
Expected: all PASS

**Step 4: Commit**

```bash
git add tests/
git commit -m "feat: integration tests for full detection-to-config flow"
```

---

### Task 7: Final Polish

**Step 1: Verify the app works end-to-end with the real phone**

```bash
cd /home/k1/public/phone_backup && python phone_backup.py
```

**Step 2: Run full test suite**

```bash
python -m pytest tests/ -v
```

**Step 3: Final commit with all files**

```bash
git add -A
git commit -m "feat: phone backup TUI system with safe transfers"
```
