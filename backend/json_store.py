"""Atomic, corruption-tolerant I/O for installed.json.

installed.json is the single source of truth for what Moddy may later uninstall, toggle, or
restore — losing it strands mod files in game directories with nothing tracking them. Every
reader/writer of the file (mods, modloaders, profiles, vanilla snapshots, workshop tombstones)
goes through this module so three guarantees hold in one place:

- A corrupt file doesn't brick the plugin. A file that exists but won't parse is quarantined
  aside as <name>.corrupt-<ts> (preserved for hand recovery, never overwritten) and an empty
  store is returned, so the plugin stays usable and the next save starts a fresh file. Without
  the quarantine, a corrupt file both read back as empty AND made every save fail forever —
  each save re-reads the file to preserve the other sections — so the library looked wiped and
  nothing could persist again until someone SSH'd in.

- Writes are atomic AND durable: tmp file, fsync, rename over, fsync the directory. Mod
  placement is already crash-safe via the install journal's fsync'd write-ahead log; without
  the same care here a power cut could still zero the store itself (the classic
  rename-without-fsync hole).

- A once-per-session .bak snapshot is taken the first time the file reads back clean, as a
  recovery source of last resort. After a quarantine the snapshot is skipped for the rest of
  the session, so a store rebuilt from scratch can't clobber the last good copy.

(Named json_store, not store/settings/etc — backend module names must not collide with
decky_loader's own modules, which shadow ours on the import path.)
"""

import json
import os
import shutil
import time

import decky

# Paths already snapshotted to .bak this session — or barred from it because the file was
# quarantined, in which case the previous session's good .bak must survive.
_bak_done: set[str] = set()

# Quarantines that happened this session, so the UI can tell the user their library was
# reset on purpose (and where the old file went) instead of showing a silently empty list.
_quarantined: list[dict] = []


def quarantine_events() -> list[dict]:
    """[{file, to, at}] for every quarantine this session. `to` is None if the corrupt
    file could not be moved aside (it stays in place and saves will keep failing)."""
    return list(_quarantined)


def _fsync_dir(dirpath: str) -> None:
    try:
        fd = os.open(dirpath, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass


def _quarantine(path: str) -> None:
    dest = f"{path}.corrupt-{int(time.time())}"
    n = 0
    while os.path.lexists(dest):
        n += 1
        dest = f"{path}.corrupt-{int(time.time())}-{n}"
    event = {"file": os.path.basename(path), "to": None, "at": time.time()}
    try:
        os.replace(path, dest)
        event["to"] = os.path.basename(dest)
        decky.logger.error(
            f"{os.path.basename(path)} is corrupt — quarantined to {os.path.basename(dest)}, "
            f"starting a fresh store")
    except OSError as e:
        decky.logger.error(f"{os.path.basename(path)} is corrupt and could not be quarantined: {e}")
    _quarantined.append(event)
    _bak_done.add(path)


def _backup_once(path: str) -> None:
    if path in _bak_done:
        return
    _bak_done.add(path)
    try:
        shutil.copy2(path, path + ".bak")
    except OSError as e:
        decky.logger.warning(f"Could not snapshot {os.path.basename(path)}.bak: {e}")


def read(path: str) -> dict:
    """Parse a JSON store file. Missing file or transient I/O error reads as {}; a file that
    exists but won't parse as a JSON object is quarantined (see module docstring) and reads
    as {} so later writes can rebuild it."""
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r") as f:
            data = json.load(f)
    except ValueError:  # JSONDecodeError / UnicodeDecodeError — the file itself is bad
        _quarantine(path)
        return {}
    except OSError as e:
        decky.logger.error(f"Failed to read {path}: {e}")
        return {}
    if not isinstance(data, dict):
        _quarantine(path)
        return {}
    _backup_once(path)
    return data


def write(path: str, data: dict) -> bool:
    """Persist `data` atomically and durably (fsync file + dir). Returns True on success.

    Every write stamps a schema number (for future format migrations) and the plugin
    version that wrote the file (so a user-supplied store in a bug report says which
    Moddy produced it)."""
    data["schema"] = 1
    version = getattr(decky, "DECKY_PLUGIN_VERSION", None)
    if version:
        data["written_by"] = version
    tmp = path + ".tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        _fsync_dir(os.path.dirname(path))
        return True
    except Exception as e:
        decky.logger.error(f"Failed to save {path}: {e}")
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        return False


def update_section(path: str, key: str, value) -> bool:
    """Read-modify-write one top-level section, preserving the others."""
    full = read(path)
    full[key] = value
    return write(path, full)
