"""Integration tests for FOMOD handling in the zip_nativepc (MHW) install path.

Phase 3 behaviour: a FOMOD with real choices PARKS (returns {"needs_fomod", "fomod": <model>}) so
the UI can show the wizard; the install resumes with the wizard's JSON selections through the same
`variant` channel as a variant id. A FOMOD with no real choice (all forced) still auto-installs.
These exercise the full pipeline: built zip -> extract -> resolve/park -> stage -> nativePC merge.
"""
import asyncio
import json
import os
import tempfile
import unittest

from _harness import mods, utils, make_mod, make_game, reset_store, stub_download
import mods_fomod


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
    """Required Core + a SelectExactlyOne colour group (Red default, Blue alternative) — a real
    choice, so it parks."""
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


COLOR_WRITES = {
    "fomod/ModuleConfig.xml": select_one_color(),
    "00 Core/nativePC/pl/core.tex": b"core",
    "01 Red/nativePC/pl/red.tex": b"red",
    "02 Blue/nativePC/pl/blue.tex": b"blue",
}


def select_color_and_size():
    """Required Core + TWO SelectExactlyOne groups in one step (Colour: Red default/Blue; Size: Small
    default/Large). Lets a collection name ONE group and leave the other to its default — exercising
    the merge-over-defaults in selections_from_choices."""
    return module_config(
        '<installStep name="Opts"><optionalFileGroups>'
        '<group name="Pick" type="SelectExactlyOne"><plugins>'
        '<plugin name="Red"><description>r</description>'
        '<files><folder source="01 Red\\nativePC" destination=""/></files>'
        '<typeDescriptor><type name="Optional"/></typeDescriptor></plugin>'
        '<plugin name="Blue"><description>b</description>'
        '<files><folder source="02 Blue\\nativePC" destination=""/></files>'
        '<typeDescriptor><type name="Optional"/></typeDescriptor></plugin>'
        '</plugins></group>'
        '<group name="Size" type="SelectExactlyOne"><plugins>'
        '<plugin name="Small"><description>s</description>'
        '<files><folder source="03 Small\\nativePC" destination=""/></files>'
        '<typeDescriptor><type name="Optional"/></typeDescriptor></plugin>'
        '<plugin name="Large"><description>l</description>'
        '<files><folder source="04 Large\\nativePC" destination=""/></files>'
        '<typeDescriptor><type name="Optional"/></typeDescriptor></plugin>'
        '</plugins></group>'
        '</optionalFileGroups></installStep>',
        required='<folder source="00 Core\\nativePC" destination=""/>')


TWO_GROUP_WRITES = {
    "fomod/ModuleConfig.xml": select_color_and_size(),
    "00 Core/nativePC/pl/core.tex": b"core",
    "01 Red/nativePC/pl/red.tex": b"red",
    "02 Blue/nativePC/pl/blue.tex": b"blue",
    "03 Small/nativePC/pl/small.tex": b"small",
    "04 Large/nativePC/pl/large.tex": b"large",
}


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

    # --- parking on a real choice -------------------------------------------

    def test_fomod_with_choices_parks_with_serialized_model(self):
        res, _ = self._install(COLOR_WRITES)
        self.assertIsInstance(res, dict)
        self.assertTrue(res.get("needs_fomod"))
        model = res["fomod"]
        self.assertEqual(model["moduleName"], "FOMOD Test")
        group = model["steps"][0]["groups"][0]
        self.assertEqual(group["type"], "SelectExactlyOne")
        self.assertEqual([p["name"] for p in group["plugins"]], ["Red", "Blue"])
        self.assertEqual(model["default"], [[0, 0, [0]]])  # default picks Red (first selectable)
        # nothing installed yet — it's parked
        self.assertFalse(self.exists("nativePC/pl/core.tex"))

    def test_resume_installs_the_chosen_option(self):
        self._install(COLOR_WRITES)                                   # parks, keeps cached extract
        sel = json.dumps([[0, 0, [1]]])                               # choose Blue (plugin idx 1)
        res, mod = self._install(COLOR_WRITES, variant=sel)          # resume
        self.assertIs(res, True)
        self.assertTrue(self.exists("nativePC/pl/core.tex"), "required Core installed")
        self.assertTrue(self.exists("nativePC/pl/blue.tex"), "chosen Blue installed")
        self.assertFalse(self.exists("nativePC/pl/red.tex"), "unchosen Red NOT installed")
        self.assertEqual(sorted(mods.get_installed_record(self.game.appid, mod.id)["paths"]),
                         ["nativePC/pl/blue.tex", "nativePC/pl/core.tex"])

    def test_resume_with_defaults_sentinel_installs_default(self):
        self._install(COLOR_WRITES)
        res, _ = self._install(COLOR_WRITES, variant=mods_fomod.FOMOD_DEFAULTS)
        self.assertIs(res, True)
        self.assertTrue(self.exists("nativePC/pl/red.tex"), "default (Red) installed")
        self.assertFalse(self.exists("nativePC/pl/blue.tex"))

    # --- collection install: replay choices / never park --------------------

    def test_collection_choices_install_the_curator_pick(self):
        # A collection passes the curator's choices (by name) as the variant; no park, install Blue.
        choices = {"options": [{"name": "Colour", "groups": [
            {"name": "Pick", "choices": [{"name": "Blue", "idx": 1}]}]}]}
        res, _ = self._install(COLOR_WRITES, variant=json.dumps(choices))
        self.assertIs(res, True)
        self.assertTrue(self.exists("nativePC/pl/core.tex"))
        self.assertTrue(self.exists("nativePC/pl/blue.tex"))
        self.assertFalse(self.exists("nativePC/pl/red.tex"))

    def test_collection_auto_sentinel_installs_defaults_without_parking(self):
        # A choice FOMOD with no recorded choices in a collection must use defaults, not park.
        res, _ = self._install(COLOR_WRITES, variant=mods_fomod.COLLECTION_AUTO)
        self.assertIs(res, True)
        self.assertTrue(self.exists("nativePC/pl/red.tex"))   # default = Red
        self.assertFalse(self.exists("nativePC/pl/blue.tex"))

    def test_collection_unmatched_choice_name_silently_uses_default(self):
        # THE risky path: a curator's choice whose step/group names don't match this ModuleConfig
        # (e.g. the mod was re-authored). selections_from_choices skips the unmatched names, so the
        # install proceeds under DEFAULTS — it must NOT park, crash, or install nothing. Verifying
        # the placed files (default Red) is the only way to catch a silent wrong-variant install.
        choices = {"options": [{"name": "WrongStep", "groups": [
            {"name": "WrongGroup", "choices": [{"name": "Blue", "idx": 1}]}]}]}
        res, _ = self._install(COLOR_WRITES, variant=json.dumps(choices))
        self.assertIs(res, True)
        self.assertTrue(self.exists("nativePC/pl/core.tex"))
        self.assertTrue(self.exists("nativePC/pl/red.tex"), "unmatched names fall back to default Red")
        self.assertFalse(self.exists("nativePC/pl/blue.tex"))

    def test_collection_partial_choices_keep_defaults_for_unnamed_groups(self):
        # Curator names only the Colour group (Blue); the Size group it doesn't mention must keep its
        # default (Small), not get wiped. Guards the `defaults.update(curator)` merge.
        choices = {"options": [{"name": "Opts", "groups": [
            {"name": "Pick", "choices": [{"name": "Blue", "idx": 1}]}]}]}
        res, _ = self._install(TWO_GROUP_WRITES, variant=json.dumps(choices))
        self.assertIs(res, True)
        self.assertTrue(self.exists("nativePC/pl/blue.tex"), "named group -> curator pick (Blue)")
        self.assertTrue(self.exists("nativePC/pl/small.tex"), "unnamed group -> default (Small)")
        self.assertFalse(self.exists("nativePC/pl/red.tex"))
        self.assertFalse(self.exists("nativePC/pl/large.tex"))

    def test_collection_invalid_choice_falls_back_to_defaults(self):
        # Curator names the right group but an out-of-range plugin idx (stale vs a changed config):
        # the pick is dropped, leaving the SelectExactlyOne empty -> resolve raises -> the collection
        # path retries with defaults rather than failing the whole collection. Installs default Red.
        choices = {"options": [{"name": "Colour", "groups": [
            {"name": "Pick", "choices": [{"name": "Gone", "idx": 5}]}]}]}
        res, _ = self._install(COLOR_WRITES, variant=json.dumps(choices))
        self.assertIs(res, True)
        self.assertTrue(self.exists("nativePC/pl/red.tex"), "invalid pick -> defaults (Red)")
        self.assertFalse(self.exists("nativePC/pl/blue.tex"))

    # --- no real choice still auto-installs (Phase 2 behaviour) --------------

    def test_no_choice_fomod_auto_installs_without_parking(self):
        # A single SelectAll group with one plugin is fully forced — no wizard needed.
        mc = module_config(
            '<installStep name="S"><optionalFileGroups>'
            '<group name="G" type="SelectAll"><plugins>'
            '<plugin name="P"><description>d</description>'
            '<files><folder source="payload\\nativePC" destination=""/></files>'
            '<typeDescriptor><type name="Required"/></typeDescriptor></plugin>'
            '</plugins></group></optionalFileGroups></installStep>')
        res, _ = self._install({"fomod/ModuleConfig.xml": mc, "payload/nativePC/pl/p.tex": b"p"})
        self.assertIs(res, True)
        self.assertTrue(self.exists("nativePC/pl/p.tex"))

    def test_without_fomod_same_folders_park_as_variants(self):
        # Control: the SAME option folders WITHOUT a fomod config are read as 3 variants (the old
        # heuristic) — proving the FOMOD path changes behaviour.
        res, _ = self._install({
            "00 Core/nativePC/pl/core.tex": b"core",
            "01 Red/nativePC/pl/red.tex": b"red",
            "02 Blue/nativePC/pl/blue.tex": b"blue",
        })
        self.assertIsInstance(res, dict)
        self.assertTrue(res.get("needs_variant"))
        self.assertEqual(len(res["variants"]), 3)

    # --- robustness ----------------------------------------------------------

    def test_case_insensitive_source_resolution(self):
        # No-choice FOMOD so it installs directly; ModuleConfig references ARMORS\\RED\\... but the
        # archive ships armors/red/... (different case) — must still resolve.
        mc = module_config(
            '<installStep name="S"><optionalFileGroups>'
            '<group name="G" type="SelectAll"><plugins>'
            '<plugin name="P"><description>d</description>'
            '<files><folder source="ARMORS\\RED\\nativePC" destination=""/></files>'
            '<typeDescriptor><type name="Required"/></typeDescriptor></plugin>'
            '</plugins></group></optionalFileGroups></installStep>')
        res, _ = self._install({"fomod/ModuleConfig.xml": mc, "armors/red/nativePC/pl/red.tex": b"red"})
        self.assertIs(res, True)
        self.assertTrue(self.exists("nativePC/pl/red.tex"))

    def test_priority_later_op_overwrites(self):
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
        mc = (
            '<config><moduleName>U</moduleName><installSteps order="Explicit">'
            '<installStep name="S"><visible><dependencies operator="And">'
            '<fileDependency file="x.esp" state="Active"/></dependencies></visible>'
            '<optionalFileGroups><group name="G" type="SelectAll"><plugins>'
            '<plugin name="P"><description>d</description>'
            '<files><folder source="payload\\nativePC" destination=""/></files>'
            '<typeDescriptor><type name="Required"/></typeDescriptor></plugin>'
            '</plugins></group></optionalFileGroups></installStep></installSteps></config>')
        res, _ = self._install({"fomod/ModuleConfig.xml": mc, "nativePC/pl/fallback.tex": b"fb"})
        self.assertIs(res, True)
        self.assertTrue(self.exists("nativePC/pl/fallback.tex"))

    def test_resumed_fomod_install_toggle_and_uninstall(self):
        self._install(COLOR_WRITES)
        _, mod = self._install(COLOR_WRITES, variant=mods_fomod.FOMOD_DEFAULTS)
        run(mods.toggle_mod(self.game, self.install_dir, mod.id, False))
        self.assertFalse(self.exists("nativePC/pl/core.tex"))
        self.assertTrue(self.exists("nativePC/pl/core.tex.disabled"))
        run(mods.toggle_mod(self.game, self.install_dir, mod.id, True))
        self.assertTrue(self.exists("nativePC/pl/core.tex"))
        run(mods.uninstall_mod(self.game, self.install_dir, mod.id))
        self.assertFalse(self.exists("nativePC/pl/core.tex"))
        self.assertIsNone(mods.get_installed_record(self.game.appid, mod.id))


if __name__ == "__main__":
    unittest.main()
