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


class _StagedInstall:
    """All-or-nothing placement of already-staged files into a live directory tree that may be
    shared with the base game and other mods (BepInEx/plugins, the RE4 game root, MelonLoader's
    Mods/). Files are copied in one at a time; every file created and every file moved aside is
    tracked, so leaving the block with an exception (including utils.InstallCancelledError) rolls
    the tree back to exactly its prior state. Leaving cleanly commits — the set-aside backups are
    dropped and the new files stay.

    Unlike a single-rename swap, the live tree IS mutated as place()/retire() run; the guarantee
    is transactional (undo on failure), not crash-atomic across the commit itself — but the commit
    is local file copies only (no network), so the failure window is tiny. Folder-owning installs
    (a mod that wholly owns BepInEx/plugins/<name>/) should use a directory swap instead.

    Contract: call retire() for a previous install's paths BEFORE place()-ing the new files, so a
    new file never displaces one this same transaction just wrote.

        with _StagedInstall(install_dir) as txn:
            for rel in previous_paths:
                txn.retire(rel)
            for src_abs, rel in placements:
                txn.place(src_abs, rel)
        set_installed_record(...)   # reached only if the commit succeeded
    """

    def __init__(self, install_dir: str):
        self.install_dir = install_dir
        self._created: list[str] = []                 # abs paths of files we newly wrote
        self._displaced: list[tuple[str, str]] = []   # (abs original, abs backup) moved aside
        self._displaced_origins: set[str] = set()      # fast membership for the above
        self._made_dirs: list[str] = []               # abs dirs we created (to prune on rollback)

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
                self._set_aside(cand)

    def __enter__(self) -> "_StagedInstall":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is None:
            self._commit()
        else:
            self._rollback()
        return False  # never suppress the exception

    def _commit(self) -> None:
        for _orig, bak in self._displaced:
            _discard(bak)  # drop the set-aside original (file or retired directory)

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
