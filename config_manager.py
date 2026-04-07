"""Manage per-phone YAML configuration files."""
import yaml
from pathlib import Path

SKIP_FOLDERS = {"Android", ".thumbnails", ".trash"}

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
    for pattern, dest in DEST_MAPPING_RULES:
        if pattern in source_path:
            return dest
    folder_name = Path(source_path).name
    return f"other/{folder_name}"


def scan_phone_folders(mount_path: Path) -> list[Path]:
    folders = []
    if not mount_path.exists():
        return folders
    for storage_root in sorted(mount_path.iterdir()):
        if not storage_root.is_dir() or storage_root.name.startswith("."):
            continue
        for level1 in sorted(storage_root.iterdir()):
            if not level1.is_dir() or level1.name.startswith("."):
                continue
            if level1.name in SKIP_FOLDERS:
                continue
            has_subfolders = False
            for level2 in sorted(level1.iterdir()):
                if not level2.is_dir() or level2.name.startswith("."):
                    continue
                if level2.name in SKIP_FOLDERS:
                    continue
                folders.append(level2.relative_to(mount_path))
                has_subfolders = True
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
    save_phone_config(config, phones_dir)
    return config


def load_phone_config(phone_id: str, phones_dir: Path) -> dict:
    config_file = phones_dir / f"{phone_id}.yaml"
    if not config_file.exists():
        return None
    with open(config_file) as f:
        return yaml.safe_load(f)


def save_phone_config(config: dict, phones_dir: Path) -> None:
    phones_dir.mkdir(parents=True, exist_ok=True)
    config_file = phones_dir / f"{config['phone_id']}.yaml"
    with open(config_file, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
