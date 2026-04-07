# Phone Backup

A terminal tool for backing up Android phones over USB (MTP).
Connect your phone, run the tool, select folders, and go.

## Features

- Detects MTP-connected Android phones automatically
- Per-phone YAML config with sync (keep on phone) and move (delete from phone) modes
- Interactive terminal UI with keyboard navigation
  - Arrow keys to browse, spacebar to toggle, s/m to reassign folders between sections
  - Folder sizes scanned in background
  - Progress bar with ETA during transfers
- Three transfer backends, auto-selected for best speed
- Safe transfers: copies to temp file first, verifies size, then renames
- Incremental: skips files already backed up (same name and size)
- No filename collisions: moved files go into dated folders
- Config editor mode to manage multiple phones

## Screenshots

### Backup UI

Select folders to sync or move, grouped by destination:

![Backup UI](docs/screenshots/backup_ui.svg)

### Transfer Progress

Progress bar with file counts, sizes, ETA, and live log:

![Transfer Progress](docs/screenshots/progress.svg)

### Config Mode

Pick a phone to edit its config (`backup_phone config`):

![Config Mode](docs/screenshots/config_mode.svg)

## Quick Start

Install dependencies:

```bash
pip install -r requirements.txt
```

Connect phone in file transfer (MTP) mode, then run:

```bash
python phone_backup.py
```

First run auto-detects your phone and creates a config file. Your editor opens so you can sort folders into sync or move sections. Subsequent runs show the folder list. Select what to back up and press Start.

## Usage

```bash
python phone_backup.py          # Main backup interface
python phone_backup.py config   # Edit phone configs
```

## Transfer Backends

The tool auto-detects the fastest available method for copying files:

| Backend | Speed | Requirements |
|---|---|---|
| **adb** | Fastest (2-5x) | USB debugging enabled on phone |
| **gio** | Fast | `gio` command (most Linux desktops) |
| **python** | Fallback | Always works, no extras needed |

### adb (fastest)

Uses Android Debug Bridge to pull files directly, bypassing MTP. 2-5x faster than MTP for large transfers.

To enable USB debugging on your phone:
1. Go to **Settings > About Phone**, tap **Build Number** 7 times to unlock Developer Options
2. Go to **Settings > Developer Options**, enable **USB Debugging**
3. Reconnect the USB cable and accept the prompt on your phone

The tool detects adb automatically and prompts you with these instructions if adb is installed but the phone is not connected via USB debugging.

### gio (fast)

Uses the GVFS optimized MTP backend via the `gio` command. Faster than reading through the FUSE mount with Python. Available on most Linux desktops with GNOME or similar. No extra setup needed.

### python (fallback)

Reads and writes files directly through the MTP FUSE mount using 4MB chunks. Slowest but always works.

## Backup Structure

Backups are organized per phone under `BACKUP_BASE` (default `~/backup/`):

```
~/backup/<phone_id>/
  sync/                          # synced folders (overwritten in place)
    audio/music/
    documents/
    ...
  move/                          # moved folders in dated subfolders
    2026-04-06/
      photos/camera/
      audio/recordings/
    2026-04-07/
      photos/camera/
```

Sync folders are updated in place on each run. Move folders go into a dated subfolder (`YYYY-MM-DD`), so a new photo with the same filename as an old one never overwrites the old backup.

## Safety

- All copies go through a temp file (`.tmp_` prefix) first. The temp file is verified (size check) before being renamed to the final name.
- Source files on the phone are never deleted until the copy is confirmed.
- If the transfer is interrupted (disconnect, crash, Ctrl+C), no files are lost. Partial `.tmp_` files are cleaned up on the next run.
- Existing files with the same name and size are skipped (incremental backup).
- Move backups use dated folders, preventing filename collisions across backup sessions.

## Keyboard Controls

| Key | Action |
|---|---|
| Up/Down | Move between folders |
| Space | Toggle folder selection |
| s | Move folder to sync section |
| m | Move folder to move section |
| a | Select all |
| n | Deselect all |
| Tab | Switch between folder list and actions |
| Left/Right | Move between actions |
| Enter | Activate action or toggle folder |
| q | Quit |

## Config Files

Each phone gets a YAML config in the `phones/` directory. See [docs/example_config.yaml](docs/example_config.yaml) for the format.

Three sections:
- **sync**: backup and keep on phone
- **move**: backup and delete from phone
- **undecided**: not yet categorized (shown as warning in the UI)

The `phones/` directory is a private git submodule. To set up your own:

1. Create a private repo on GitHub
2. `git submodule add <your-repo-url> phones`
3. Or just create a `phones/` directory locally (it works without being a submodule)

## Configuration

Edit the top of `phone_backup.py` to change:

- `BACKUP_BASE`: where backups go (default: `~/backup/`)
- `PHONES_DIR`: where phone configs live (default: `./phones/`)

## Project Structure

```
phone_backup.py          # main script with terminal UI
detector.py              # MTP phone detection via GVFS, adb detection
config_manager.py        # YAML config management and folder mapping
transfer.py              # safe file transfer with three backends
phones/                  # per-phone config files (private submodule)
docs/example_config.yaml # sample config for reference
tests/                   # test suite (33 tests)
```

## Requirements

- Python 3.12+
- PyYAML
- Linux with GVFS (for MTP phone access)
- Optional: adb (Android Debug Bridge) for faster transfers
