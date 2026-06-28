"""Integration tests for FOMOD handling in the zip_nativepc (MHW) install path.

These exercise the full pipeline: a built zip containing fomod/ModuleConfig.xml is "downloaded",
extracted, the FOMOD is resolved under default options, staged, and merged into nativePC/ by the
existing loose-file machinery. The headline behaviour is the silent-wrong fix: a real FOMOD's option
folders are NOT mutually-exclusive variants, so the old _detect_variants heuristic would park and let
the user pick one folder (dropping the required Core); FOMOD resolution installs Core + the default
option together.
"""
import asyncio
import os
import tempfile
import unittest

from _harness import mods, utils, make_mod, make_game, reset_store, stub_download


def run(coro):
    return asyncio.run(coro)


def module_config(steps_xml, required=""):
    return (
        '<config><moduleName>FOMOD Test</moduleName>'
        '<installSteps order="Explicit">' + steps_xml + '</installSteps>'
        + (('<requiredInstallFiles>' + required + '</requiredInstallFiles>') if required else '')
        + '</config>'
    )


def select_one_color():
    """A required Core + a SelectExactlyOne colour group (Red default, Blue alternative)."""
    return module_config(
        '<installStep name="Colour"><optionalFileGroups>'
        '<group name="Pick" type="SelectExactlyOne"><plugins>'
        '<plugin name="Red"><description>r</description>'
        '<files><folder source="01 Red\\nativePC" destination=""/></files>'
        '<typeDescriptor><type name="Optional"/></typeDescriptor></plugin>'
        '<plugin name="Blue"><description>b</description>'
        '<files><folder source="02 Blue\\nativePC" destination=""/></files>'
        '<typeDescriptor><type name="Optional"/></typeDescriptor></plugin>'
        '</plugins></group></optionalFileGroups></installStep>',
        required='<folder source="00 Core\\nativePC" destination=""/>')


class FomodInstallTest(unittest.TestCase):
    def setUp(self):
        reset_store()
        self.install_dir = tempfile.mkdtemp(prefix="moddy-fomod-")
        self.game = make_game(mods_dir="")  # MHW: mods live in the game root
        self._orig_download = utils.download

    def tearDown(self):
        utils.download = self._orig_download

    def exists(self, rel):
        return os.path.exists(os.path.join(self.install_dir, rel))

    def read(self, rel):
        with open(os.path.join(self.install_dir, rel), "rb") as f:
            return f.read()

    def _install(self, writes, mod_id="m", filename="Cool", variant=None):
        utils.download = stub_download(writes=writes)
        mod = make_mod(mod_id=mod_id, filename=filename, install_type="zip_nativepc")
        res = run(mods._install_mod_zip_nativepc(self.game, self.install_dir, mod, "1.0", "http://x", variant))
        return res, mod

    # --- the headline behaviour ---------------------------------------------

    def test_fomod_installs_core_plus_default_option(self):
        res, mod = self._install({
            "fomod/ModuleConfig.xml": select_one_color(),
            "00 Core/nativePC/pl/core.tex": b"core",
            "01 Red/nativePC/pl/red.tex": b"red",
            "02 Blue/nativePC/pl/blue.tex": b"blue",
        })
        self.assertIs(res, True, "FOMOD should install directly, not park for a variant")
        self.assertTrue(self.exists("nativePC/pl/core.tex"), "required Core must be installed")
        self.assertTrue(self.exists("nativePC/pl/red.tex"), "default option (Red) must be installed")
        self.assertFalse(self.exists("nativePC/pl/blue.tex"), "non-default option must NOT be installed")
        self.assertEqual(
            sorted(mods.get_installed_record(mod.id)["paths"]),
            ["nativePC/pl/core.tex", "nativePC/pl/red.tex"],
        )

    def test_without_fomod_same_folders_park_as_variants(self):
        # Control: the SAME option folders WITHOUT a fomod/ManifestConfig are read as 3 mutually
        # exclusive variants -> the old behaviour parks and would drop Core. This is what FOMOD fixes.
        res, _ = self._install({
            "00 Core/nativePC/pl/core.tex": b"core",
            "01 Red/nativePC/pl/red.tex": b"red",
            "02 Blue/nativePC/pl/blue.tex": b"blue",
        })
        self.assertIsInstance(res, dict)
        self.assertTrue(res.get("needs_variant"))
        self.assertEqual(len(res["variants"]), 3)

    def test_fomod_takes_precedence_over_variant_parking(self):
        # Even though Core/Red/Blue each contain a nativePC tree (so _detect_variants would see 3),
        # the presence of fomod/ModuleConfig.xml means we resolve instead of parking.
        res, _ = self._install({
            "fomod/ModuleConfig.xml": select_one_color(),
            "00 Core/nativePC/pl/core.tex": b"core",
            "01 Red/nativePC/pl/red.tex": b"red",
            "02 Blue/nativePC/pl/blue.tex": b"blue",
        })
        self.assertNotIsInstance(res, dict)
        self.assertIs(res, True)

    # --- robustness ----------------------------------------------------------

    def test_case_insensitive_source_resolution(self):
        # ModuleConfig references ARMORS\\RED\\... but the archive ships armors/red/... (different
        # case). FOMOD paths are case-insensitive; the Deck FS is not, so this must still resolve.
        mc = module_config(
            '<installStep name="S"><optionalFileGroups>'
            '<group name="G" type="SelectAll"><plugins>'
            '<plugin name="P"><description>d</description>'
            '<files><folder source="ARMORS\\RED\\nativePC" destination=""/></files>'
            '<typeDescriptor><type name="Required"/></typeDescriptor></plugin>'
            '</plugins></group></optionalFileGroups></installStep>')
        res, _ = self._install({
            "fomod/ModuleConfig.xml": mc,
            "armors/red/nativePC/pl/red.tex": b"red",
        })
        self.assertIs(res, True)
        self.assertTrue(self.exists("nativePC/pl/red.tex"))

    def test_priority_later_op_overwrites(self):
        # A higher-priority option folder writing the same path must win over the required Core.
        mc = module_config(
            '<installStep name="S"><optionalFileGroups>'
            '<group name="G" type="SelectAll"><plugins>'
            '<plugin name="Over"><description>d</description>'
            '<files><folder source="over\\nativePC" destination="" priority="5"/></files>'
            '<typeDescriptor><type name="Optional"/></typeDescriptor></plugin>'
            '</plugins></group></optionalFileGroups></installStep>',
            required='<folder source="core\\nativePC" destination="" priority="0"/>')
        res, _ = self._install({
            "fomod/ModuleConfig.xml": mc,
            "core/nativePC/pl/shared.tex": b"core-version",
            "over/nativePC/pl/shared.tex": b"override-version",
        })
        self.assertIs(res, True)
        self.assertEqual(self.read("nativePC/pl/shared.tex"), b"override-version")

    def test_unsupported_fomod_falls_back_to_legacy(self):
        # A FOMOD using a construct we can't evaluate (fileDependency) must NOT be force-resolved;
        # it falls back to the legacy variant/merge path (here: a single root nativePC tree).
        mc = (
            '<config><moduleName>U</moduleName><installSteps order="Explicit">'
            '<installStep name="S"><visible><dependencies operator="And">'
            '<fileDependency file="x.esp" state="Active"/></dependencies></visible>'
            '<optionalFileGroups><group name="G" type="SelectAll"><plugins>'
            '<plugin name="P"><description>d</description>'
            '<files><folder source="payload\\nativePC" destination=""/></files>'
            '<typeDescriptor><type name="Required"/></typeDescriptor></plugin>'
            '</plugins></group></optionalFileGroups></installStep></installSteps></config>')
        res, _ = self._install({
            "fomod/ModuleConfig.xml": mc,
            "nativePC/pl/fallback.tex": b"fb",
        })
        self.assertIs(res, True)
        self.assertTrue(self.exists("nativePC/pl/fallback.tex"))

    def test_fomod_install_toggle_and_uninstall(self):
        _, mod = self._install({
            "fomod/ModuleConfig.xml": select_one_color(),
            "00 Core/nativePC/pl/core.tex": b"core",
            "01 Red/nativePC/pl/red.tex": b"red",
            "02 Blue/nativePC/pl/blue.tex": b"blue",
        })
        run(mods.toggle_mod(self.game, self.install_dir, mod.id, False))
        self.assertFalse(self.exists("nativePC/pl/core.tex"))
        self.assertTrue(self.exists("nativePC/pl/core.tex.disabled"))
        run(mods.toggle_mod(self.game, self.install_dir, mod.id, True))
        self.assertTrue(self.exists("nativePC/pl/core.tex"))
        run(mods.uninstall_mod(self.game, self.install_dir, mod.id))
        self.assertFalse(self.exists("nativePC/pl/core.tex"))
        self.assertFalse(self.exists("nativePC/pl/red.tex"))
        self.assertIsNone(mods.get_installed_record(mod.id))


if __name__ == "__main__":
    unittest.main()
