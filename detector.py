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
    while parts and len(parts[-1]) >= 8 and parts[-1].isalnum() and parts[-1].isupper():
        parts.pop()
    if not parts:
        return phone_id
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
