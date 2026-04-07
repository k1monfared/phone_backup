# Phone Backup System Design

## Overview

A Python TUI application that detects USB-connected Android phones via MTP,
manages per-phone backup configurations, and performs safe sync/move operations
with an interactive interface.

## Architecture

### Components

1. **Phone Detector** - Scans `/run/user/{uid}/gvfs/` for `mtp:host=*` mounts
2. **Config Manager** - Creates/reads per-phone YAML config files
3. **Transfer Engine** - Safe copy/move with temp files and verification
4. **TUI App** - Textual-based interface with tabs, checkboxes, progress

### Tech Stack

- Python 3.12+
- Textual (TUI framework)
- PyYAML (config files)
- pathlib (path handling)
- shutil (file operations)

## Config File Format

One YAML file per phone, stored in `phones/` directory.
Filename: `{phone_id}.yaml`

```yaml
phone_id: motorola_moto_g85_5G_ZY22KH9KPW
phone_name: Motorola Moto G85 5G
backup_root: /home/k1/backup/motorola_moto_g85_5G_ZY22KH9KPW

sync:
  - source: Internal shared storage/Music
    dest: audio/music

move:
  - source: Internal shared storage/DCIM/Camera
    dest: photos/camera

undecided:
  - source: Internal shared storage/Download
    dest: downloads
```

- `source`: relative path on the phone (under the MTP mount)
- `dest`: relative path under `backup_root`
- User moves entries between sections by cutting/pasting lines

## Destination Mapping Heuristics

When a new phone is detected, all folders are placed in `undecided`
with smart default destination mappings:

| Source pattern                         | Dest mapping        |
|----------------------------------------|---------------------|
| DCIM/Camera                            | photos/camera       |
| Pictures/Screenshots                   | photos/screenshots  |
| WhatsApp/Media/WhatsApp Images         | photos/messaging    |
| WhatsApp/Media/WhatsApp Video          | videos/messaging    |
| WhatsApp/Media/WhatsApp Audio          | audio/messaging     |
| Telegram images                        | photos/messaging    |
| Telegram video                         | videos/messaging    |
| Movies                                 | videos/personal     |
| Music                                  | audio/music         |
| Recordings                             | audio/recordings    |
| Documents                              | documents           |
| Download                               | downloads           |
| Other                                  | other/{foldername}   |

## TUI Layout

```
+-- Phone Backup ------------------------------------+
| Connected: Motorola Moto G85 5G (ZY22KH9KPW)      |
|                                                    |
| [!] 5 folders still in 'undecided' - edit config   |
|                                                    |
| [ Sync ] [ Move ]                                  |
| +------------------------------------------------+ |
| | [x] Select All                                 | |
| | [x] Internal shared storage/Music        120MB | |
| | [x] Internal shared storage/Documents     45MB | |
| | [ ] Internal shared storage/Podcasts      2.1G | |
| +------------------------------------------------+ |
|                                                    |
| Overall: 234 / 1,203 files (19%)  ETA: 3m 42s     |
| [=================>                    ] 19%       |
| Current: IMG_20260401_143022.jpg  4.2MB / 4.2MB   |
|                                                    |
| [ Start Backup ]  [ Cancel ]                       |
+----------------------------------------------------+
```

## Safe Transfer Strategy

1. Enumerate all files in selected source folders
2. Skip files already present in dest (same name + same size)
3. Copy each file to `dest/.tmp_{filename}`
4. Verify copied file size matches source
5. Rename `.tmp_{filename}` to final filename
6. For move operations only: delete source file after verified copy
7. Log every operation to `phones/{phone_id}.transfer.log`

If interrupted mid-transfer:
- `.tmp_*` files in dest are incomplete, safe to delete on next run
- Source files are never deleted until copy is verified
- Next run picks up where it left off (skips already-copied files)

## Progress Tracking

- Pre-scan counts total files and bytes across all selected folders
- Overall progress bar: files completed / total files, with ETA
- Per-file display: current filename, bytes copied / file size
- Textual ProgressBar widget for smooth visual updates

## File Structure

```
phone_backup/
  phone_backup.py        # main script + TUI
  phones/                # per-phone config files
    {phone_id}.yaml
    {phone_id}.transfer.log
  requirements.txt       # textual, pyyaml
```

## Parameters

Top of script, user-configurable:
- `BACKUP_BASE`: defaults to `~/backup/`
- `PHONES_DIR`: defaults to `./phones/`
