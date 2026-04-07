import os
import tempfile
from pathlib import Path
from detector import detect_phones, get_gvfs_base


def test_detect_phones_finds_mtp_mounts(tmp_path):
    mtp_dir = tmp_path / "mtp:host=motorola_moto_g85_5G_ZY22KH9KPW"
    mtp_dir.mkdir()
    (mtp_dir / "Internal shared storage").mkdir()
    phones = detect_phones(gvfs_path=tmp_path)
    assert len(phones) == 1
    assert phones[0]["phone_id"] == "motorola_moto_g85_5G_ZY22KH9KPW"
    assert phones[0]["mount_path"] == mtp_dir


def test_detect_phones_ignores_non_mtp(tmp_path):
    (tmp_path / "gphoto2:host=some_camera").mkdir()
    (tmp_path / "smb-share:server=nas").mkdir()
    phones = detect_phones(gvfs_path=tmp_path)
    assert len(phones) == 0


def test_detect_phones_multiple(tmp_path):
    (tmp_path / "mtp:host=phone_A").mkdir()
    (tmp_path / "mtp:host=phone_B").mkdir()
    phones = detect_phones(gvfs_path=tmp_path)
    assert len(phones) == 2
    ids = {p["phone_id"] for p in phones}
    assert ids == {"phone_A", "phone_B"}


def test_detect_phones_extracts_display_name():
    from detector import phone_display_name
    assert phone_display_name("motorola_moto_g85_5G_ZY22KH9KPW") == "Motorola Moto G85 5G"


def test_get_storage_roots(tmp_path):
    from detector import get_storage_roots
    mount = tmp_path / "mtp:host=phone_A"
    mount.mkdir()
    (mount / "Internal shared storage").mkdir()
    (mount / "SD card").mkdir()
    roots = get_storage_roots(mount)
    assert set(roots) == {"Internal shared storage", "SD card"}
