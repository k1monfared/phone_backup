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
    (tmp_path / "a.jpg").write_bytes(b"x" * 100)
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.png").write_bytes(b"y" * 200)
    (tmp_path / ".tmp_partial").write_bytes(b"z" * 50)
    files = enumerate_files(tmp_path)
    names = {f.name for f in files}
    assert names == {"a.jpg", "b.png"}
    assert ".tmp_partial" not in names


def test_should_skip_file_already_exists(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    dst = tmp_path / "dst"
    dst.mkdir()
    (src / "photo.jpg").write_bytes(b"x" * 100)
    (dst / "photo.jpg").write_bytes(b"x" * 100)
    assert should_skip_file(src / "photo.jpg", dst / "photo.jpg") is True


def test_should_not_skip_different_size(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    dst = tmp_path / "dst"
    dst.mkdir()
    (src / "photo.jpg").write_bytes(b"x" * 100)
    (dst / "photo.jpg").write_bytes(b"x" * 50)
    assert should_skip_file(src / "photo.jpg", dst / "photo.jpg") is False


def test_should_not_skip_missing(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "photo.jpg").write_bytes(b"x" * 100)
    assert should_skip_file(src / "photo.jpg", tmp_path / "dst" / "photo.jpg") is False


def test_safe_copy_file(tmp_path):
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
    assert not list(dst.glob(".tmp_*"))


def test_safe_copy_file_creates_parent_dirs(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "file.txt").write_bytes(b"data")
    dest_file = tmp_path / "dst" / "deep" / "nested" / "file.txt"
    result = safe_copy_file(src / "file.txt", dest_file)
    assert result is True
    assert dest_file.exists()


def test_clean_tmp_files(tmp_path):
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
    stats = TransferStats(total_files=10, total_bytes=1000)
    assert stats.percent_files == 0.0
    stats.file_done(100)
    assert stats.files_done == 1
    assert stats.bytes_done == 100
    assert stats.percent_files == 10.0
