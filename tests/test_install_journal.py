"""Tests for the write-ahead install journal (crash-atomic mod placement).

A _StagedInstall journals its intended ops (fsync'd, write-ahead) and marks COMMIT once every file is
placed. recover_journals(), run at startup, replays any journal a crash left behind: NO commit marker
-> roll back (remove created files, restore displaced originals); WITH a marker -> roll forward (keep
the files, drop leftover backups). This is what guarantees "a mod is installed or not" across a
power-loss mid-commit.
"""
import os
import tempfile
import unittest

import _harness  # noqa: F401 — installs the fake decky (with a temp runtime dir for the journals)
import install_txn
from install_txn import _StagedInstall, recover_journals, _journals_dir, _STAGED_BAK_SUFFIX


def write(path, s):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(s)


def read(path):
    with open(path) as f:
        return f.read()


class InstallJournalTest(unittest.TestCase):
    def setUp(self):
        self.install_dir = tempfile.mkdtemp(prefix="moddy-jrnl-")
        self.staging = tempfile.mkdtemp(prefix="moddy-stage-")
        for n in os.listdir(_journals_dir()):  # start clean
            os.remove(os.path.join(_journals_dir(), n))

    def _fake_journal(self, lines):
        path = os.path.join(_journals_dir(), "ij_test.log")
        with open(path, "w") as f:
            f.write("\n".join(lines) + "\n")
        return path

    def p(self, rel):
        return os.path.join(self.install_dir, rel)

    def test_clean_install_leaves_no_journal(self):
        src = os.path.join(self.staging, "a.txt"); write(src, "data")
        with _StagedInstall(self.install_dir) as txn:
            txn.place(src, "sub/a.txt")
        self.assertTrue(os.path.exists(self.p("sub/a.txt")))
        self.assertEqual(os.listdir(_journals_dir()), [])  # journal deleted on a clean commit

    def test_failed_install_rolls_back_and_leaves_no_journal(self):
        # A raise inside the block triggers the in-process rollback AND drops the journal.
        src = os.path.join(self.staging, "a.txt"); write(src, "data")
        with self.assertRaises(RuntimeError):
            with _StagedInstall(self.install_dir) as txn:
                txn.place(src, "a.txt")
                raise RuntimeError("boom")
        self.assertFalse(os.path.exists(self.p("a.txt")))
        self.assertEqual(os.listdir(_journals_dir()), [])

    def test_recover_rolls_back_interrupted_commit(self):
        # Simulate the on-disk state of a power-loss mid-commit (no COMMIT marker): one brand-new file
        # created, and one stock file displaced (its original set aside to .moddy-bak).
        write(self.p("new.tex"), "newmod")                                   # created
        write(self.p("keep.tex"), "modded")                                  # displaced: new content in place
        write(self.p("keep.tex" + _STAGED_BAK_SUFFIX), "original")            # the set-aside original
        self._fake_journal([self.install_dir, "place\tnew.tex\t0", "place\tkeep.tex\t1"])  # no COMMIT
        recover_journals()
        self.assertFalse(os.path.exists(self.p("new.tex")), "created file removed")
        self.assertEqual(read(self.p("keep.tex")), "original", "displaced original restored")
        self.assertFalse(os.path.exists(self.p("keep.tex" + _STAGED_BAK_SUFFIX)), "backup consumed")
        self.assertEqual(os.listdir(_journals_dir()), [], "journal consumed")

    def test_recover_rolls_forward_committed_install(self):
        # COMMIT marker present → every file landed → keep them, just clear a leftover backup.
        write(self.p("new.tex"), "newmod")
        write(self.p("keep.tex"), "modded")
        write(self.p("keep.tex" + _STAGED_BAK_SUFFIX), "original")            # bak-drop didn't reach it
        self._fake_journal([self.install_dir, "place\tnew.tex\t0", "place\tkeep.tex\t1", "COMMIT"])
        recover_journals()
        self.assertEqual(read(self.p("new.tex")), "newmod", "created file kept")
        self.assertEqual(read(self.p("keep.tex")), "modded", "committed content kept")
        self.assertFalse(os.path.exists(self.p("keep.tex" + _STAGED_BAK_SUFFIX)), "leftover backup dropped")
        self.assertEqual(os.listdir(_journals_dir()), [])

    def test_recover_leaves_untouched_original_when_displace_never_happened(self):
        # Journal recorded intent to displace keep.tex, but the crash hit before the set-aside (no bak,
        # original still in place). Rollback must NOT delete it.
        write(self.p("keep.tex"), "original")  # untouched original, no bak
        self._fake_journal([self.install_dir, "place\tkeep.tex\t1"])  # displaced intent, no COMMIT
        recover_journals()
        self.assertEqual(read(self.p("keep.tex")), "original", "untouched original left intact")


if __name__ == "__main__":
    unittest.main()
