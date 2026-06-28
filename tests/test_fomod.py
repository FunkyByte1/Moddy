"""Tests for the FOMOD engine (backend/fomod.py).

Two layers:
  - Corpus: every real ModuleConfig.xml in tests/fixtures/fomod/ (mined from MHW collection choices)
    must parse cleanly, report no unsupported constructs, and resolve under its default selections.
  - Synthetic: hand-built ModuleConfigs pin the branching machinery the MHW corpus exercises (flags,
    step visibility, dependencyType, group validation, Required/NotUsable) plus the bits it doesn't
    (conditionalFileInstalls, unsupported fileDependency fail-loud).

fomod.py is pure (no `decky`), so this test imports it directly without the _harness fake.
"""
import gzip
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))
import fomod  # noqa: E402

FIXTURE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "fomod")


def load_fixture(name):
    with gzip.open(os.path.join(FIXTURE_DIR, name), "rb") as f:
        return f.read()


def fixture_names():
    return sorted(n for n in os.listdir(FIXTURE_DIR) if n.endswith(".xml.gz"))


# a minimal valid ModuleConfig builder for synthetic tests
def cfg(steps_xml, required="", conditional="", module_deps=""):
    return (
        '<config>'
        '<moduleName>Synthetic</moduleName>'
        + module_deps
        + '<installSteps order="Explicit">' + steps_xml + '</installSteps>'
        + (('<requiredInstallFiles>' + required + '</requiredInstallFiles>') if required else '')
        + (('<conditionalFileInstalls><patterns>' + conditional + '</patterns></conditionalFileInstalls>')
           if conditional else '')
        + '</config>'
    )


class TestCorpus(unittest.TestCase):
    """Every real fixture must parse + resolve under defaults without surprises."""

    def test_all_fixtures_parse_clean(self):
        names = fixture_names()
        self.assertGreaterEqual(len(names), 10, "expected the harvested MHW corpus")
        for name in names:
            with self.subTest(fixture=name):
                model = fomod.parse(load_fixture(name))
                self.assertTrue(model.install_steps, "no install steps")
                self.assertTrue(any(g.plugins for s in model.install_steps for g in s.groups))
                # the MHW corpus uses only flag-based constructs -> nothing unsupported
                self.assertEqual(model.unsupported, set(), "unexpected unsupported: %s" % model.unsupported)

    def test_all_fixtures_resolve_under_defaults(self):
        for name in fixture_names():
            with self.subTest(fixture=name):
                model = fomod.parse(load_fixture(name))
                plan = fomod.resolve(model, fomod.default_selections(model))
                self.assertTrue(plan.operations, "default resolve produced no file ops")
                # priorities must be non-decreasing (sorted, last-writer-wins)
                prios = [o.priority for o in plan.operations]
                self.assertEqual(prios, sorted(prios))

    def test_known_fixture_5818(self):
        model = fomod.parse(load_fixture("mhw_5818.xml.gz"))
        self.assertEqual(model.module_name, "Harvest Armor Ver.R")
        self.assertEqual(len(model.install_steps), 12)
        self.assertTrue(model.required_install_files, "expected requiredInstallFiles")
        # every group in this mod is SelectExactlyOne
        gtypes = {g.type for s in model.install_steps for g in s.groups}
        self.assertEqual(gtypes, {"SelectExactlyOne"})
        # at least one step is gated by a flag (visible/flagDependency)
        self.assertTrue(any(s.visible is not None for s in model.install_steps))

    def test_stress_fixture_5076(self):
        model = fomod.parse(load_fixture("mhw_5076.xml.gz"))  # 62 steps, 355 groups
        self.assertGreater(len(model.install_steps), 50)
        plan = fomod.resolve(model, fomod.default_selections(model))
        self.assertTrue(plan.operations)


class TestPathSemantics(unittest.TestCase):
    def test_folder_and_file_paths_normalised(self):
        model = fomod.parse(cfg(
            '<installStep name="S"><optionalFileGroups>'
            '<group name="G" type="SelectAll"><plugins>'
            '<plugin name="P"><description>d</description>'
            '<files>'
            '<folder source="A\\sub\\nativePC" destination="" priority="2"/>'
            '<file source="x\\y.txt" destination="dst\\here" priority="7"/>'
            '</files>'
            '<typeDescriptor><type name="Optional"/></typeDescriptor>'
            '</plugin></plugins></group></optionalFileGroups></installStep>'))
        ops = model.install_steps[0].groups[0].plugins[0].files
        folder, fileop = ops
        self.assertEqual((folder.source, folder.destination, folder.is_folder), ("A/sub/nativePC", "", True))
        self.assertEqual((fileop.source, fileop.destination, fileop.is_folder), ("x/y.txt", "dst/here", False))
        self.assertEqual((folder.priority, fileop.priority), (2, 7))


class TestSelectionValidation(unittest.TestCase):
    def setUp(self):
        self.model = fomod.parse(cfg(
            '<installStep name="S"><optionalFileGroups>'
            '<group name="Pick" type="SelectExactlyOne"><plugins>'
            '<plugin name="A"><description>a</description>'
            '<files><folder source="A" destination=""/></files>'
            '<conditionFlags><flag name="picked">A</flag></conditionFlags>'
            '<typeDescriptor><type name="Optional"/></typeDescriptor></plugin>'
            '<plugin name="B"><description>b</description>'
            '<files><folder source="B" destination=""/></files>'
            '<typeDescriptor><type name="Optional"/></typeDescriptor></plugin>'
            '</plugins></group></optionalFileGroups></installStep>',
            required='<folder source="core" destination=""/>'))

    def test_exactly_one_ok(self):
        plan = fomod.resolve(self.model, {(0, 0): {0}})
        sources = [o.source for o in plan.operations]
        self.assertIn("A", sources)
        self.assertIn("core", sources)        # requiredInstallFiles always present
        self.assertNotIn("B", sources)
        self.assertEqual(plan.flags.get("picked"), "A")

    def test_exactly_one_rejects_zero(self):
        with self.assertRaises(fomod.FomodSelectionError):
            fomod.resolve(self.model, {(0, 0): set()})

    def test_exactly_one_rejects_two(self):
        with self.assertRaises(fomod.FomodSelectionError):
            fomod.resolve(self.model, {(0, 0): {0, 1}})


class TestRequiredAndNotUsable(unittest.TestCase):
    def setUp(self):
        self.model = fomod.parse(cfg(
            '<installStep name="S"><optionalFileGroups>'
            '<group name="G" type="SelectAny"><plugins>'
            '<plugin name="Req"><description>r</description>'
            '<files><folder source="req" destination=""/></files>'
            '<typeDescriptor><type name="Required"/></typeDescriptor></plugin>'
            '<plugin name="No"><description>n</description>'
            '<files><folder source="no" destination=""/></files>'
            '<typeDescriptor><type name="NotUsable"/></typeDescriptor></plugin>'
            '</plugins></group></optionalFileGroups></installStep>'))

    def test_required_forced_in_even_if_unselected(self):
        plan = fomod.resolve(self.model, {(0, 0): set()})
        self.assertIn("req", [o.source for o in plan.operations])

    def test_notusable_dropped_even_if_selected(self):
        plan = fomod.resolve(self.model, {(0, 0): {1}})
        self.assertNotIn("no", [o.source for o in plan.operations])


class TestFlagsAndVisibility(unittest.TestCase):
    """A flag set in step 1 gates whether step 2 is shown."""

    def build(self):
        return fomod.parse(cfg(
            # step 1: pick A (sets flag) or B (sets nothing)
            '<installStep name="S1"><optionalFileGroups>'
            '<group name="Pick" type="SelectExactlyOne"><plugins>'
            '<plugin name="A"><description>a</description><files><folder source="A" destination=""/></files>'
            '<conditionFlags><flag name="want_extra">On</flag></conditionFlags>'
            '<typeDescriptor><type name="Optional"/></typeDescriptor></plugin>'
            '<plugin name="B"><description>b</description><files><folder source="B" destination=""/></files>'
            '<typeDescriptor><type name="Optional"/></typeDescriptor></plugin>'
            '</plugins></group></optionalFileGroups></installStep>'
            # step 2: only visible if want_extra==On; installs "extra"
            '<installStep name="S2">'
            '<visible><dependencies operator="And"><flagDependency flag="want_extra" value="On"/></dependencies></visible>'
            '<optionalFileGroups><group name="Extra" type="SelectAll"><plugins>'
            '<plugin name="E"><description>e</description><files><folder source="extra" destination=""/></files>'
            '<typeDescriptor><type name="Required"/></typeDescriptor></plugin>'
            '</plugins></group></optionalFileGroups></installStep>'))

    def test_step_visible_when_flag_set(self):
        model = self.build()
        plan = fomod.resolve(model, {(0, 0): {0}, (1, 0): {0}})  # pick A -> step 2 shown
        self.assertIn("extra", [o.source for o in plan.operations])

    def test_step_hidden_when_flag_unset(self):
        model = self.build()
        plan = fomod.resolve(model, {(0, 0): {1}, (1, 0): {0}})  # pick B -> step 2 hidden, selection ignored
        self.assertNotIn("extra", [o.source for o in plan.operations])


class TestDependencyType(unittest.TestCase):
    def test_effective_type_switches_on_flag(self):
        model = fomod.parse(cfg(
            '<installStep name="S"><optionalFileGroups>'
            '<group name="G" type="SelectAny"><plugins>'
            '<plugin name="P"><description>d</description><files><folder source="p" destination=""/></files>'
            '<typeDescriptor><dependencyType>'
            '<defaultType name="Optional"/>'
            '<patterns><pattern>'
            '<dependencies operator="And"><flagDependency flag="x" value="On"/></dependencies>'
            '<type name="Recommended"/>'
            '</pattern></patterns>'
            '</dependencyType></typeDescriptor></plugin>'
            '</plugins></group></optionalFileGroups></installStep>'))
        td = model.install_steps[0].groups[0].plugins[0].type_descriptor
        self.assertEqual(td.effective_type({}), "Optional")
        self.assertEqual(td.effective_type({"x": "On"}), "Recommended")


class TestConditionalFileInstalls(unittest.TestCase):
    def build(self):
        return fomod.parse(cfg(
            '<installStep name="S"><optionalFileGroups>'
            '<group name="Pick" type="SelectExactlyOne"><plugins>'
            '<plugin name="A"><description>a</description><files><folder source="A" destination=""/></files>'
            '<conditionFlags><flag name="variant">red</flag></conditionFlags>'
            '<typeDescriptor><type name="Optional"/></typeDescriptor></plugin>'
            '<plugin name="B"><description>b</description><files><folder source="B" destination=""/></files>'
            '<conditionFlags><flag name="variant">blue</flag></conditionFlags>'
            '<typeDescriptor><type name="Optional"/></typeDescriptor></plugin>'
            '</plugins></group></optionalFileGroups></installStep>',
            conditional=(
                '<pattern><dependencies operator="And"><flagDependency flag="variant" value="red"/></dependencies>'
                '<files><folder source="red_patch" destination=""/></files></pattern>')))

    def test_conditional_included_when_flag_matches(self):
        plan = fomod.resolve(self.build(), {(0, 0): {0}})  # variant=red
        self.assertIn("red_patch", [o.source for o in plan.operations])

    def test_conditional_skipped_when_flag_differs(self):
        plan = fomod.resolve(self.build(), {(0, 0): {1}})  # variant=blue
        self.assertNotIn("red_patch", [o.source for o in plan.operations])


class TestPriorityOrdering(unittest.TestCase):
    def test_ops_sorted_by_priority_stable(self):
        model = fomod.parse(cfg(
            '<installStep name="S"><optionalFileGroups>'
            '<group name="G" type="SelectAll"><plugins>'
            '<plugin name="P"><description>d</description><files>'
            '<folder source="late" destination="" priority="9"/>'
            '<folder source="early" destination="" priority="1"/>'
            '</files><typeDescriptor><type name="Optional"/></typeDescriptor></plugin>'
            '</plugins></group></optionalFileGroups></installStep>',
            required='<folder source="req0" destination=""/>'))
        plan = fomod.resolve(model, {(0, 0): {0}})
        order = [o.source for o in plan.operations]
        self.assertLess(order.index("req0"), order.index("early"))   # priority 0 first
        self.assertLess(order.index("early"), order.index("late"))   # 1 before 9


class TestUnsupportedFailLoud(unittest.TestCase):
    def test_filedependency_recorded_and_evaluation_raises(self):
        model = fomod.parse(cfg(
            '<installStep name="S2">'
            '<visible><dependencies operator="And">'
            '<fileDependency file="other.esp" state="Active"/>'
            '</dependencies></visible>'
            '<optionalFileGroups><group name="G" type="SelectAll"><plugins>'
            '<plugin name="P"><description>d</description><files><folder source="p" destination=""/></files>'
            '<typeDescriptor><type name="Required"/></typeDescriptor></plugin>'
            '</plugins></group></optionalFileGroups></installStep>'))
        self.assertIn("fileDependency", model.unsupported)
        # resolving must surface it rather than silently guess the step's visibility
        with self.assertRaises(fomod.FomodUnsupported):
            fomod.resolve(model, {(0, 0): {0}})

    def test_malformed_xml_raises_parse_error(self):
        with self.assertRaises(fomod.FomodParseError):
            fomod.parse("<config><installSteps><notclosed></config>")

    def test_wrong_root_raises_parse_error(self):
        with self.assertRaises(fomod.FomodParseError):
            fomod.parse("<notconfig/>")


if __name__ == "__main__":
    unittest.main()
