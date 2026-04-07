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
    assert "Internal shared storage/DCIM/.thumbnails" not in folder_strs
    assert "Internal shared storage/Android/data" not in folder_strs

def test_create_phone_config(tmp_path):
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
    assert len(loaded["undecided"]) == 2

def test_load_phone_config(tmp_path):
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
