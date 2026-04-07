"""Safe file transfer engine with progress tracking."""
import subprocess
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
    files = []
    if not folder.exists():
        return files
    for item in sorted(folder.rglob("*")):
        if item.is_file() and not item.name.startswith(".tmp_"):
            files.append(item)
    return files


def should_skip_file(src: Path, dst: Path) -> bool:
    if not dst.exists():
        return False
    return src.stat().st_size == dst.stat().st_size


# ---------------------------------------------------------------------------
# Copy backends
# ---------------------------------------------------------------------------

def _copy_python(
    src: Path,
    dst: Path,
    progress_callback: Callable[[int], None] = None,
    chunk_size: int = 4 * 1024 * 1024,
) -> bool:
    """Copy via Python file I/O. Slowest but always works."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp_dst = dst.parent / f".tmp_{dst.name}"
    try:
        src_size = src.stat().st_size
        with open(src, "rb") as fsrc, open(tmp_dst, "wb") as fdst:
            while True:
                chunk = fsrc.read(chunk_size)
                if not chunk:
                    break
                fdst.write(chunk)
                if progress_callback:
                    progress_callback(len(chunk))
        tmp_size = tmp_dst.stat().st_size
        if tmp_size != src_size:
            tmp_dst.unlink(missing_ok=True)
            return False
        tmp_dst.rename(dst)
        return True
    except (OSError, IOError):
        tmp_dst.unlink(missing_ok=True)
        return False


def _copy_gio(src: Path, dst: Path) -> bool:
    """Copy via gio (GVFS optimized MTP backend). Faster than Python I/O."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp_dst = dst.parent / f".tmp_{dst.name}"
    try:
        src_size = src.stat().st_size
        result = subprocess.run(
            ["gio", "copy", str(src), str(tmp_dst)],
            capture_output=True, timeout=600,
        )
        if result.returncode != 0:
            tmp_dst.unlink(missing_ok=True)
            return False
        tmp_size = tmp_dst.stat().st_size
        if tmp_size != src_size:
            tmp_dst.unlink(missing_ok=True)
            return False
        tmp_dst.rename(dst)
        return True
    except (subprocess.TimeoutExpired, OSError):
        tmp_dst.unlink(missing_ok=True)
        return False


def _mtp_source_to_adb_path(src: Path) -> str | None:
    """
    Convert an MTP mount path to an adb-compatible path.
    /run/user/1000/gvfs/mtp:host=.../Internal shared storage/DCIM/Camera/photo.jpg
    -> /sdcard/DCIM/Camera/photo.jpg

    Both "Internal shared storage" and "android" storage roots map to /sdcard/.
    """
    parts = src.parts
    # Find the storage root (after the mtp:host=... directory)
    mtp_idx = None
    for i, p in enumerate(parts):
        if p.startswith("mtp:host="):
            mtp_idx = i
            break
    if mtp_idx is None:
        return None
    # parts after mtp:host=... are: storage_root / rest_of_path
    after_mtp = parts[mtp_idx + 1:]
    if len(after_mtp) < 2:
        return None
    # Skip the storage root name, rest maps to /sdcard/
    rest = "/".join(after_mtp[1:])
    return f"/sdcard/{rest}"


def _copy_adb(src: Path, dst: Path, adb_serial: str = None) -> bool:
    """Copy via adb pull. Fastest, requires USB debugging enabled."""
    adb_path = _mtp_source_to_adb_path(src)
    if adb_path is None:
        return False

    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp_dst = dst.parent / f".tmp_{dst.name}"
    try:
        cmd = ["adb"]
        if adb_serial:
            cmd.extend(["-s", adb_serial])
        cmd.extend(["pull", adb_path, str(tmp_dst)])

        result = subprocess.run(cmd, capture_output=True, timeout=600)
        if result.returncode != 0:
            tmp_dst.unlink(missing_ok=True)
            return False

        # Verify size against the MTP-visible source
        src_size = src.stat().st_size
        tmp_size = tmp_dst.stat().st_size
        if tmp_size != src_size:
            tmp_dst.unlink(missing_ok=True)
            return False
        tmp_dst.rename(dst)
        return True
    except (subprocess.TimeoutExpired, OSError):
        tmp_dst.unlink(missing_ok=True)
        return False


def safe_copy_file(
    src: Path,
    dst: Path,
    backend: str = "python",
    adb_serial: str = None,
    progress_callback: Callable[[int], None] = None,
) -> bool:
    """
    Copy a file safely using the specified backend.
    All backends use temp file + rename for crash safety.
    """
    if backend == "adb" and adb_serial:
        return _copy_adb(src, dst, adb_serial)
    if backend == "gio":
        return _copy_gio(src, dst)
    return _copy_python(src, dst, progress_callback=progress_callback)


# ---------------------------------------------------------------------------
# Cleanup and folder transfer
# ---------------------------------------------------------------------------

def clean_tmp_files(folder: Path) -> int:
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
    backend: str = "python",
    adb_serial: str = None,
    progress_callback: Callable[[], None] = None,
    log_callback: Callable[[str], None] = None,
    cancel_event=None,
) -> None:
    clean_tmp_files(dst_folder)
    files = enumerate_files(src_folder)
    for src_file in files:
        if cancel_event and cancel_event.is_set():
            return
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

        success = safe_copy_file(
            src_file, dst_file,
            backend=backend,
            adb_serial=adb_serial,
            progress_callback=on_chunk,
        )
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
