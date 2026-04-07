"""Integration test: full flow from detection to config creation."""
import yaml
from pathlib import Path
from detector import detect_phones
from config_manager import create_phone_config, load_phone_config


def test_full_flow_new_phone(tmp_path):
    """Simulate detecting a new phone and creating its config."""
    gvfs = tmp_path / "gvfs"
    mount = gvfs / "mtp:host=samsung_galaxy_s24_R5ABC123"
    storage = mount / "Internal shared storage"
    (storage / "DCIM" / "Camera").mkdir(parents=True)
    (storage / "Music").mkdir(parents=True)
    (storage / "Download").mkdir(parents=True)
    (storage / "WhatsApp" / "Media" / "WhatsApp Images").mkdir(parents=True)
    (storage / "DCIM" / "Camera" / "IMG_001.jpg").write_bytes(b"x" * 1024)
    (storage / "DCIM" / "Camera" / "IMG_002.jpg").write_bytes(b"y" * 2048)
    (storage / "Music" / "song.mp3").write_bytes(b"z" * 512)

    phones = detect_phones(gvfs_path=gvfs)
    assert len(phones) == 1
    phone = phones[0]
    assert phone["phone_id"] == "samsung_galaxy_s24_R5ABC123"

    phones_dir = tmp_path / "phones"
    phones_dir.mkdir()
    config = create_phone_config(
        phone_id=phone["phone_id"],
        display_name=phone["display_name"],
        mount_path=phone["mount_path"],
        phones_dir=phones_dir,
        backup_base=tmp_path / "backup",
    )

    assert config["phone_id"] == "samsung_galaxy_s24_R5ABC123"
    assert len(config["undecided"]) >= 3  # DCIM, Music, Download, WhatsApp
    assert config["sync"] == []
    assert config["move"] == []

    dests = {e["source"]: e["dest"] for e in config["undecided"]}
    assert dests.get("Internal shared storage/DCIM") == "photos/camera"
    assert dests.get("Internal shared storage/Music") == "audio/music"
    assert dests.get("Internal shared storage/Download") == "downloads"

    loaded = load_phone_config("samsung_galaxy_s24_R5ABC123", phones_dir)
    assert loaded == config


def test_full_transfer_flow(tmp_path):
    """Test the complete transfer flow: scan, copy, verify."""
    from transfer import TransferStats, transfer_folder

    src = tmp_path / "src"
    (src / "photos").mkdir(parents=True)
    (src / "photos" / "img1.jpg").write_bytes(b"photo1" * 100)
    (src / "photos" / "img2.jpg").write_bytes(b"photo2" * 200)
    (src / "docs").mkdir(parents=True)
    (src / "docs" / "readme.txt").write_bytes(b"hello")

    dst = tmp_path / "dst"
    stats = TransferStats(total_files=3, total_bytes=600 + 1200 + 5)

    transfer_folder(
        src_folder=src,
        dst_folder=dst,
        stats=stats,
        delete_source=False,
    )

    assert stats.files_done == 3
    assert stats.files_failed == 0
    assert (dst / "photos" / "img1.jpg").exists()
    assert (dst / "photos" / "img2.jpg").exists()
    assert (dst / "docs" / "readme.txt").exists()
    assert (dst / "docs" / "readme.txt").read_bytes() == b"hello"

    # Source files still exist (sync mode)
    assert (src / "photos" / "img1.jpg").exists()


def test_transfer_move_deletes_source(tmp_path):
    """Move mode: source files deleted after copy."""
    from transfer import TransferStats, transfer_folder

    src = tmp_path / "src"
    src.mkdir()
    (src / "file.txt").write_bytes(b"data")

    dst = tmp_path / "dst"
    stats = TransferStats(total_files=1, total_bytes=4)

    transfer_folder(
        src_folder=src,
        dst_folder=dst,
        stats=stats,
        delete_source=True,
    )

    assert (dst / "file.txt").exists()
    assert not (src / "file.txt").exists()


def test_transfer_skips_existing(tmp_path):
    """Already-backed-up files are skipped."""
    from transfer import TransferStats, transfer_folder

    src = tmp_path / "src"
    src.mkdir()
    (src / "existing.txt").write_bytes(b"same content")

    dst = tmp_path / "dst"
    dst.mkdir()
    (dst / "existing.txt").write_bytes(b"same content")

    stats = TransferStats(total_files=1, total_bytes=12)

    transfer_folder(
        src_folder=src,
        dst_folder=dst,
        stats=stats,
        delete_source=False,
    )

    assert stats.files_skipped == 1
    assert stats.files_done == 1
