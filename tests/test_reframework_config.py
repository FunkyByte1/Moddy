"""Tests for REFramework's post-install config write (_apply_config_files).

REFramework reads a single fixed file, `re2_fw_config.txt`, in the game ROOT (next to the .exe /
dinput8.dll) for EVERY RE Engine game — not a `reframework/config.txt`, and its format is
`Key=Value`, not space-separated. Moddy pre-seeds `LooseFileLoader_Enabled=true` there so loose
`natives/` mods are read on first launch. These tests pin the filename + format and the key-level
merge that preserves the ~80 other keys REFramework writes on a clean exit.
"""
import os
import tempfile
import unittest

from _harness import registry  # installs the fake decky before importing backend modules
import modloaders


def _reframework_loader():
    # Mirror registry/modloaders/reframework.json's config_files.
    return registry.ModloaderInfo(
        id="reframework", name="REFramework",
        source=registry.ModSource(type="github", owner="praydog", repo="REFramework", asset="RE4.zip"),
        files=["dinput8.dll"], indicator="dinput8.dll",
        config_files={"re2_fw_config.txt": "LooseFileLoader_Enabled=true\n"},
    )


class ReframeworkConfigTest(unittest.TestCase):
    def setUp(self):
        self.install_dir = tempfile.mkdtemp(prefix="moddy-ref-cfg-")
        self.cfg = os.path.join(self.install_dir, "re2_fw_config.txt")

    def _read(self):
        with open(self.cfg) as f:
            return f.read()

    def test_fresh_write_lands_in_game_root_with_equals_format(self):
        modloaders._apply_config_files(self.install_dir, _reframework_loader())
        # Written to the game root under the name REFramework actually reads...
        self.assertTrue(os.path.isfile(self.cfg))
        self.assertFalse(os.path.exists(os.path.join(self.install_dir, "reframework", "config.txt")))
        # ...in Key=Value form, the value REFramework parses.
        self.assertEqual(self._read().strip(), "LooseFileLoader_Enabled=true")

    def test_merge_flips_existing_key_and_preserves_others(self):
        # REFramework rewrites the full config (sorted Key=Value) on a clean exit, with the loader
        # defaulting to false. Re-applying must flip just that key and keep everything else.
        existing = (
            "Camera_Enabled=false\n"
            "LooseFileLoader_Enabled=false\n"
            "LooseFileLoader_LogAccessedFiles=false\n"
            "VR_AsyncRendering_V3=true\n"
        )
        with open(self.cfg, "w") as f:
            f.write(existing)
        modloaders._apply_config_files(self.install_dir, _reframework_loader())
        lines = self._read().splitlines()
        self.assertIn("LooseFileLoader_Enabled=true", lines)
        self.assertNotIn("LooseFileLoader_Enabled=false", lines)
        # Unrelated keys are untouched, and no duplicate key is appended.
        self.assertIn("Camera_Enabled=false", lines)
        self.assertIn("VR_AsyncRendering_V3=true", lines)
        self.assertEqual(sum(1 for l in lines if modloaders._config_key(l) == "LooseFileLoader_Enabled"), 1)


if __name__ == "__main__":
    unittest.main()
