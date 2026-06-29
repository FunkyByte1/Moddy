"""Atomic file-placement primitive shared by the mod and modloader installers.

_StagedInstall commits already-staged files into a live directory tree all-or-nothing: on a clean
exit the new files stay and the set-aside backups are dropped; on any exception (including a
cancelled download) the tree is rolled back to exactly its prior state. It deliberately has no
dependency on the mods/modloaders modules so both can import it without a cycle.
"""
import os
import decky


# Suffix for a file set aside mid-install (displaced by an incoming file, or retired from a
# previous install). On a clean commit these are deleted; on rollback they're moved back.
# A hard crash mid-commit can leave one behind — the startup sweep removes orphans, since a
# `*.moddy-bak` next to its live original is always disposable.
_STAGED_BAK_SUFFIX = ".moddy-bak"

# Suffix for the DURABLE backup of an original (stock) game file a mod overwrote. Unlike a
# transient .moddy-bak — which is dropped on commit — a .moddy-orig is kept across the install
# so uninstall/disable can restore the unmodded file. It is created only for displaced files
# Moddy did not place (is_foreign), and only when one doesn't already exist (first capture wins,
# so a second mod overwriting the same path can't clobber the true original). The startup sweep
# deliberately never touches it: its primary (the modded file) is normally present, which would
# make a sweep of crumb suffixes discard it.
_MODDY_ORIG_SUFFIX = ".moddy-orig"


def _discard(path: str) -> None:
    """Remove a file or a whole directory tree, best-effort (used to drop set-aside backups)."""
    import shutil
    try:
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path, ignore_errors=True)
        elif os.path.lexists(path):
            os.remove(path)
    except OSError:
        pass


# ── Write-ahead install journal ───────────────────────────────────────────────────────────
# The transaction below undoes a failed commit IN-PROCESS. But a hard power-loss DURING the commit
# (copying staged files into the live tree) leaves the process dead — no in-process rollback runs —
# and could strand a mod with some files placed and others not. To make the commit crash-atomic, each
# _StagedInstall writes a durable journal of its intended ops BEFORE doing them (fsync'd, write-ahead),
# marks COMMIT once every file is placed, and deletes the journal on a clean finish. recover_journals(),
# run once at startup before anything installs, replays any survivor: a journal WITHOUT a COMMIT marker
# was interrupted mid-placement → roll it back (remove the files it created, restore the originals it
# displaced), so the mod is cleanly absent; a journal WITH a COMMIT marker means every file landed →
# roll forward (drop leftover backups). Erring toward rollback keeps "a mod is installed or not".
_JOURNAL_DIR_NAME = "install_journals"


def _journals_dir() -> str:
    d = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, _JOURNAL_DIR_NAME)
    os.makedirs(d, exist_ok=True)
    return d


def _prune_empty_parents(path: str, stop: str) -> None:
    """Best-effort: remove now-empty parent dirs of `path`, up to (not including) `stop`."""
    d = os.path.dirname(path)
    stop = os.path.normpath(stop)
    while d and os.path.normpath(d).startswith(stop) and os.path.normpath(d) != stop:
        try:
            os.rmdir(d)
        except OSError:
            return  # not empty / gone — stop climbing
        d = os.path.dirname(d)


def _recover_one(journal_path: str) -> None:
    try:
        with open(journal_path) as f:
            lines = f.read().splitlines()
    except OSError:
        return
    if not lines:
        return
    install_dir = lines[0]
    committed = lines[-1] == "COMMIT"  # a truncated final line (power-loss mid-write) reads as NOT committed → roll back
    ops = [ln.split("\t") for ln in lines[1:] if ln and ln != "COMMIT"]

    if committed:
        # Every file landed; just clear any backup the bak-drop didn't reach.
        for parts in ops:
            if len(parts) >= 2:
                _discard(os.path.join(install_dir, parts[1]) + _STAGED_BAK_SUFFIX)
        decky.logger.info(f"install journal: completed an interrupted commit ({len(ops)} ops)")
        return

    # Not committed → undo, newest op first.
    for parts in reversed(ops):
        if len(parts) < 2:
            continue
        kind, rel = parts[0], parts[1]
        full = os.path.join(install_dir, rel)
        bak = full + _STAGED_BAK_SUFFIX
        if kind == "place" and len(parts) >= 3 and parts[2] == "0":
            _discard(full)                       # a brand-new file we created → remove it
            _prune_empty_parents(full, install_dir)
        elif os.path.lexists(bak):
            try:
                os.replace(bak, full)            # a displaced/retired original → put it back
            except OSError as e:
                decky.logger.warning(f"install journal rollback: could not restore {full}: {e}")
        # else: the displace hadn't happened yet — the original is still in place, leave it.
    decky.logger.info(f"install journal: rolled back an interrupted install ({len(ops)} ops)")


def recover_journals() -> None:
    """Replay (roll back / forward) any install journals left by a crash. Call ONCE at startup,
    before any install runs — a live install legitimately holds an open journal."""
    try:
        names = os.listdir(_journals_dir())
    except OSError:
        return
    for name in names:
        path = os.path.join(_journals_dir(), name)
        try:
            _recover_one(path)
        except Exception as e:  # noqa: BLE001 — recovery must never crash startup
            decky.logger.error(f"install journal recovery failed for {name}: {e}")
        _discard(path)


class _StagedInstall:
    """All-or-nothing placement of already-staged files into a live directory tree that may be
    shared with the base game and other mods (BepInEx/plugins, the RE4 game root, MelonLoader's
    Mods/). Files are copied in one at a time; every file created and every file moved aside is
    tracked, so leaving the block with an exception (including utils.InstallCancelledError) rolls
    the tree back to exactly its prior state. Leaving cleanly commits — the set-aside backups are
    dropped and the new files stay.

    Unlike a single-rename swap, the live tree IS mutated as place()/retire() run. Two layers cover
    failure: in-process, leaving the block with an exception rolls back here; across a hard power-loss
    mid-commit, a fsync'd write-ahead journal (see above) lets recover_journals() at next startup roll
    an interrupted install back (or a fully-placed one forward) — so a mod is never left half-placed.
    Folder-owning installs (a mod that wholly owns BepInEx/plugins/<name>/) may still use a dir swap.

    Contract: call retire() for a previous install's paths BEFORE place()-ing the new files, so a
    new file never displaces one this same transaction just wrote.

        with _StagedInstall(install_dir) as txn:
            for rel in previous_paths:
                txn.retire(rel)
            for src_abs, rel in placements:
                txn.place(src_abs, rel)
        set_installed_record(...)   # reached only if the commit succeeded
    """

    def __init__(self, install_dir: str, is_foreign=None):
        self.install_dir = install_dir
        # Optional predicate is_foreign(abs_path) -> bool: True when the file already at a
        # destination was NOT placed by Moddy (a stock game file or user-placed one). Such a
        # displaced original is preserved durably as *.moddy-orig on commit instead of dropped,
        # so the unmodded file can be restored later. Default None = treat everything as ours
        # (drop displaced backups on commit), i.e. the prior behaviour, no regression.
        self._is_foreign = is_foreign
        self._created: list[str] = []                 # abs paths of files we newly wrote
        self._displaced: list[tuple[str, str]] = []   # (abs original, abs backup) moved aside
        self._displaced_origins: set[str] = set()      # fast membership for the above
        self._made_dirs: list[str] = []               # abs dirs we created (to prune on rollback)
        self._journal = None                           # durable write-ahead log (crash recovery)
        self._journal_path: "str | None" = None

    def _open_journal(self) -> None:
        """Open a fresh write-ahead journal for this transaction (best-effort: if it can't be
        created the install still runs, just without crash recovery)."""
        import tempfile
        try:
            fd, self._journal_path = tempfile.mkstemp(prefix="ij_", suffix=".log", dir=_journals_dir())
            self._journal = os.fdopen(fd, "w")
            self._log_raw(self.install_dir)
        except OSError as e:
            decky.logger.warning(f"install journal disabled (could not open): {e}")
            self._journal = None
            self._journal_path = None

    def _log_raw(self, line: str) -> None:
        if self._journal is None:
            return
        try:
            self._journal.write(line + "\n")
            self._journal.flush()
            os.fsync(self._journal.fileno())  # write-ahead: durable BEFORE the file op it describes
        except OSError as e:
            decky.logger.warning(f"install journal write failed: {e}")

    def _close_journal(self) -> None:
        if self._journal is not None:
            try:
                self._journal.close()
            except OSError:
                pass
            self._journal = None
        if self._journal_path:
            _discard(self._journal_path)
            self._journal_path = None

    def _set_aside(self, path: str) -> None:
        """Move an existing file or directory to its .moddy-bak so it can be restored on rollback."""
        if path in self._displaced_origins:
            # Already set aside this transaction; whatever is at `path` now is something we wrote.
            return
        bak = path + _STAGED_BAK_SUFFIX
        if os.path.lexists(bak):
            _discard(bak)  # a stale crumb (file or dir) from an earlier crashed run; ours supersedes it
        os.replace(path, bak)  # same-directory rename: atomic for files and dirs, never cross-device
        self._displaced.append((path, bak))
        self._displaced_origins.add(path)

    def _ensure_parent(self, dst: str) -> None:
        """makedirs(dirname(dst)), remembering each level we actually create so rollback prunes
        exactly those (and never a directory that pre-existed or another mod shares)."""
        d = os.path.dirname(dst)
        root = os.path.normpath(self.install_dir)
        missing = []
        cur = d
        while cur and os.path.normpath(cur).startswith(root) and not os.path.isdir(cur):
            missing.append(cur)
            parent = os.path.dirname(cur)
            if parent == cur:
                break
            cur = parent
        os.makedirs(d, exist_ok=True)
        self._made_dirs.extend(missing)  # children appended before parents; pruned deepest-first

    def place(self, src_abs: str, rel: str) -> None:
        """Copy a staged file to install_dir/rel, moving aside anything already there."""
        import shutil
        dst = os.path.join(self.install_dir, rel)
        # Write-ahead: record intent (and whether dst pre-existed, so recovery knows remove-vs-restore)
        # and fsync it BEFORE touching the live tree, so a crash can't strand an unjournaled file.
        self._log_raw(f"place\t{rel}\t{1 if os.path.exists(dst) else 0}")
        self._ensure_parent(dst)
        if os.path.exists(dst):
            self._set_aside(dst)
        shutil.copy2(src_abs, dst)
        self._created.append(dst)

    def retire(self, rel: str) -> None:
        """Set aside a previous install's entry — a file or a whole directory, plus the .disabled
        form of a file — as part of this transaction, so an upgrade's old-install cleanup is undone
        if the new install fails. zip_flat records top-level entries that may be directories."""
        base = os.path.join(self.install_dir, rel)
        for cand in (base, base + ".disabled"):
            if os.path.lexists(cand):
                self._log_raw(f"retire\t{os.path.relpath(cand, self.install_dir)}")
                self._set_aside(cand)

    def __enter__(self) -> "_StagedInstall":
        self._open_journal()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        try:
            if exc_type is None:
                self._commit()
            else:
                self._rollback()
        finally:
            self._close_journal()  # a clean commit OR a completed rollback no longer needs the journal
        return False  # never suppress the exception

    def _commit(self) -> None:
        # Commit point: every place() has landed, so the new files are all present. Mark it durably —
        # recovery then rolls a survivor FORWARD (keep the files) instead of back.
        self._log_raw("COMMIT")
        for orig, bak in self._displaced:
            # Preserve a stock game file we displaced so uninstall/disable can restore vanilla,
            # rather than dropping it. Only for files Moddy didn't place, and only if no durable
            # backup exists yet (first capture wins — a later mod overwriting the same path must
            # not overwrite the true original with another mod's content).
            if self._is_foreign is not None and self._is_foreign(orig):
                durable = orig + _MODDY_ORIG_SUFFIX
                if not os.path.lexists(durable):
                    try:
                        os.replace(bak, durable)
                        continue
                    except OSError as e:
                        decky.logger.warning(f"staged-install: could not preserve original {orig}: {e}")
            _discard(bak)  # ours (or already captured) — the set-aside original is disposable

    def _rollback(self) -> None:
        # 1. Remove the files we created (newest first).
        for dst in reversed(self._created):
            try:
                if os.path.isfile(dst):
                    os.remove(dst)
            except OSError as e:
                decky.logger.warning(f"staged-install rollback: could not remove {dst}: {e}")
        # 2. Prune the directories we created, deepest first, while empty — BEFORE restoring, so a
        #    retired directory whose path we recreated is free for its backup to be moved back.
        for d in sorted(set(self._made_dirs), key=len, reverse=True):
            try:
                if os.path.isdir(d) and not os.listdir(d):
                    os.rmdir(d)
            except OSError:
                pass
        # 3. Restore everything we moved aside (files and retired directories).
        for orig, bak in self._displaced:
            try:
                if os.path.lexists(bak):
                    os.replace(bak, orig)
            except OSError as e:
                decky.logger.warning(f"staged-install rollback: could not restore {orig}: {e}")
