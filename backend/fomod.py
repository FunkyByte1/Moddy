"""FOMOD (scripted Nexus installer) engine — pure parse + resolve, no I/O.

A FOMOD mod ships a `fomod/ModuleConfig.xml` describing an install wizard: ordered steps, each with
option groups (radio/checkbox), each plugin installing files and setting condition flags that later
steps/plugins branch on. This module turns that XML into a model and, given a set of plugin
selections, resolves the exact list of file operations to perform.

Deliberately game-agnostic (see project_fomod_support): `resolve()` emits LOGICAL ops
(`source-in-archive -> destination-relative-to-mod-root`, FOMOD contents-to-destination semantics).
The caller's per-game install_type decides where the mod root lands (MHW -> nativePC/ merge, etc).

Scope (v1, matches the real MHW FOMOD corpus): installSteps, all group types, plugins, file/folder
installs, conditionFlags, typeDescriptor (static + flag-based dependencyType), step `visible` flag
conditions, requiredInstallFiles, and conditionalFileInstalls (flag-gated). Constructs the corpus
never uses — fileDependency, gameDependency, fommDependency, moduleDependencies — are PARSED but
recorded in `model.unsupported`; the integration layer is expected to fall back to a manual install
(or default-only) rather than silently guessing. Evaluating such a construct raises FomodUnsupported.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple


# ---- exceptions -------------------------------------------------------------

class FomodError(Exception):
    """Base for FOMOD engine errors."""


class FomodParseError(FomodError):
    """ModuleConfig.xml was malformed or missing required structure."""


class FomodUnsupported(FomodError):
    """A construct the v1 engine cannot evaluate (e.g. fileDependency) was reached."""


class FomodSelectionError(FomodError):
    """A selection violated its group's constraint (e.g. two picks in a SelectExactlyOne)."""


# ---- group types ------------------------------------------------------------

GROUP_TYPES = {
    "SelectExactlyOne", "SelectAtMostOne", "SelectAtLeastOne", "SelectAny", "SelectAll",
}

# plugin type-descriptor states
PLUGIN_TYPES = {"Required", "Optional", "Recommended", "NotUsable", "CouldBeUsable"}

# dependency leaf elements we cannot evaluate in v1 (no game/file state)
_UNSUPPORTED_LEAVES = {"fileDependency", "gameDependency", "fommDependency", "flagdependency_value_missing"}


# ---- model ------------------------------------------------------------------

@dataclass
class FileOp:
    """One install instruction. is_folder => copy the CONTENTS of `source` into `destination`
    (FOMOD folder semantics); else copy the single file `source` to `destination`. Paths are
    POSIX, relative, '' meaning the mod root."""
    source: str
    destination: str
    priority: int
    is_folder: bool


@dataclass
class Dependency:
    """A condition tree. `operator` combines `flag_deps` (flag==value) and nested `children`.
    `unsupported` holds names of leaves the engine can't evaluate (fileDependency, ...)."""
    operator: str  # "And" | "Or"
    flag_deps: List[Tuple[str, str]] = field(default_factory=list)
    children: List["Dependency"] = field(default_factory=list)
    unsupported: List[str] = field(default_factory=list)

    def evaluate(self, flags: Dict[str, str]) -> bool:
        if self.unsupported:
            raise FomodUnsupported("cannot evaluate dependency with " + ", ".join(sorted(set(self.unsupported))))
        results = [flags.get(f) == v for f, v in self.flag_deps]
        results += [c.evaluate(flags) for c in self.children]
        if not results:
            return True
        return all(results) if self.operator == "And" else any(results)


@dataclass
class TypeDescriptor:
    """A plugin's selectability state. `default` is the static/fallback type; `patterns` are
    (condition, type) overrides evaluated in order when flag-dependent (dependencyType)."""
    default: str
    patterns: List[Tuple[Dependency, str]] = field(default_factory=list)

    def effective_type(self, flags: Dict[str, str]) -> str:
        for cond, typ in self.patterns:
            if cond.evaluate(flags):
                return typ
        return self.default


@dataclass
class Plugin:
    name: str
    description: str
    image: Optional[str]
    files: List[FileOp]
    condition_flags: List[Tuple[str, str]]  # (flag, value) set when this plugin is selected
    type_descriptor: TypeDescriptor


@dataclass
class Group:
    name: str
    type: str
    plugins: List[Plugin]


@dataclass
class InstallStep:
    name: str
    visible: Optional[Dependency]  # step shown only if this evaluates true (None => always)
    groups: List[Group]


@dataclass
class FomodModel:
    module_name: str
    module_image: Optional[str]
    install_steps: List[InstallStep]
    required_install_files: List[FileOp]
    conditional_installs: List[Tuple[Dependency, List[FileOp]]]
    unsupported: Set[str] = field(default_factory=set)


@dataclass
class InstallPlan:
    operations: List[FileOp]       # ordered, lowest priority first (later ops overwrite earlier)
    flags: Dict[str, str]          # final flag state after the chosen path


# ---- parsing ----------------------------------------------------------------

def _ln(tag: str) -> str:
    return tag.split("}")[-1]


def _child(el, name: str):
    for c in el:
        if _ln(c.tag) == name:
            return c
    return None


def _children(el, name: str):
    return [c for c in el if _ln(c.tag) == name] if el is not None else []


def _norm(path: Optional[str]) -> str:
    """Normalise a FOMOD path: backslashes -> '/', strip surrounding slashes/space."""
    if not path:
        return ""
    return path.replace("\\", "/").strip().strip("/")


def _parse_fileops(files_el) -> List[FileOp]:
    ops: List[FileOp] = []
    if files_el is None:
        return ops
    for c in files_el:
        tag = _ln(c.tag)
        if tag not in ("file", "folder"):
            continue
        try:
            priority = int(c.get("priority", "0"))
        except (TypeError, ValueError):
            priority = 0
        ops.append(FileOp(
            source=_norm(c.get("source")),
            destination=_norm(c.get("destination")),
            priority=priority,
            is_folder=(tag == "folder"),
        ))
    return ops


def _parse_dependency(dep_el, unsupported: Set[str]) -> Dependency:
    """Parse a <dependencies>/<moduleDependencies>/<visible> condition subtree."""
    operator = (dep_el.get("operator") or "And").capitalize()
    dep = Dependency(operator=operator)
    for c in dep_el:
        tag = _ln(c.tag)
        if tag == "flagDependency":
            flag = c.get("flag")
            value = c.get("value")
            if flag is None or value is None:
                dep.unsupported.append("flagDependency(malformed)")
                unsupported.add("flagDependency(malformed)")
            else:
                dep.flag_deps.append((flag, value))
        elif tag == "dependencies":
            dep.children.append(_parse_dependency(c, unsupported))
        elif tag in ("fileDependency", "gameDependency", "fommDependency"):
            dep.unsupported.append(tag)
            unsupported.add(tag)
        # unknown leaves ignored
    return dep


def _parse_type_descriptor(td_el, unsupported: Set[str]) -> TypeDescriptor:
    if td_el is None:
        return TypeDescriptor(default="Optional")
    static = _child(td_el, "type")
    if static is not None:
        return TypeDescriptor(default=static.get("name") or "Optional")
    dep_type = _child(td_el, "dependencyType")
    if dep_type is None:
        return TypeDescriptor(default="Optional")
    default_el = _child(dep_type, "defaultType")
    default = (default_el.get("name") if default_el is not None else None) or "Optional"
    patterns: List[Tuple[Dependency, str]] = []
    patterns_el = _child(dep_type, "patterns")
    for pat in _children(patterns_el, "pattern"):
        deps_el = _child(pat, "dependencies")
        type_el = _child(pat, "type")
        if deps_el is not None and type_el is not None:
            patterns.append((_parse_dependency(deps_el, unsupported), type_el.get("name") or default))
    return TypeDescriptor(default=default, patterns=patterns)


def _parse_plugin(plugin_el, unsupported: Set[str]) -> Plugin:
    name = plugin_el.get("name") or ""
    desc_el = _child(plugin_el, "description")
    image_el = _child(plugin_el, "image")
    flags = []
    cf_el = _child(plugin_el, "conditionFlags")
    for flag_el in _children(cf_el, "flag"):
        fname = flag_el.get("name")
        if fname is not None:
            flags.append((fname, (flag_el.text or "").strip()))
    return Plugin(
        name=name,
        description=(desc_el.text or "").strip() if desc_el is not None else "",
        image=image_el.get("path") if image_el is not None else None,
        files=_parse_fileops(_child(plugin_el, "files")),
        condition_flags=flags,
        type_descriptor=_parse_type_descriptor(_child(plugin_el, "typeDescriptor"), unsupported),
    )


def _parse_group(group_el, unsupported: Set[str]) -> Group:
    gtype = group_el.get("type") or "SelectAny"
    if gtype not in GROUP_TYPES:
        unsupported.add("groupType:" + gtype)
    plugins_el = _child(group_el, "plugins")
    return Group(
        name=group_el.get("name") or "",
        type=gtype,
        plugins=[_parse_plugin(p, unsupported) for p in _children(plugins_el, "plugin")],
    )


def _parse_step(step_el, unsupported: Set[str]) -> InstallStep:
    visible = None
    visible_el = _child(step_el, "visible")
    if visible_el is not None:
        # <visible> may wrap a <dependencies>, or hold flagDependency children directly
        inner = _child(visible_el, "dependencies")
        visible = _parse_dependency(inner if inner is not None else visible_el, unsupported)
    groups = []
    ofg = _child(step_el, "optionalFileGroups")
    for g in _children(ofg, "group"):
        groups.append(_parse_group(g, unsupported))
    return InstallStep(name=step_el.get("name") or "", visible=visible, groups=groups)


def parse(xml: "str | bytes") -> FomodModel:
    """Parse a fomod/ModuleConfig.xml into a FomodModel. Raises FomodParseError on malformed XML
    or a missing <config> root. Unsupported-but-present constructs are recorded in `.unsupported`,
    not raised — the caller decides whether to proceed (flag-only mods) or fall back to manual."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as e:
        raise FomodParseError("invalid XML: %s" % e) from e
    if _ln(root.tag) != "config":
        raise FomodParseError("root element is <%s>, expected <config>" % _ln(root.tag))

    unsupported: Set[str] = set()

    name_el = _child(root, "moduleName")
    image_el = _child(root, "moduleImage")

    steps: List[InstallStep] = []
    steps_el = _child(root, "installSteps")
    for s in _children(steps_el, "installStep"):
        steps.append(_parse_step(s, unsupported))

    required = _parse_fileops(_child(root, "requiredInstallFiles"))

    conditional: List[Tuple[Dependency, List[FileOp]]] = []
    cfi_el = _child(root, "conditionalFileInstalls")
    for pat in _children(_child(cfi_el, "patterns") if cfi_el is not None else None, "pattern"):
        deps_el = _child(pat, "dependencies")
        files_el = _child(pat, "files")
        if deps_el is not None:
            conditional.append((_parse_dependency(deps_el, unsupported), _parse_fileops(files_el)))

    # a top-level moduleDependencies gate we can't evaluate is a fail-loud signal
    mod_deps = _child(root, "moduleDependencies")
    if mod_deps is not None:
        d = _parse_dependency(mod_deps, unsupported)
        if d.unsupported:
            unsupported.add("moduleDependencies")

    return FomodModel(
        module_name=(name_el.text or "").strip() if name_el is not None else "",
        module_image=image_el.get("path") if image_el is not None else None,
        install_steps=steps,
        required_install_files=required,
        conditional_installs=conditional,
        unsupported=unsupported,
    )


# ---- selection helpers ------------------------------------------------------

# a selection maps (step_index, group_index) -> set of chosen plugin indices
Selections = Dict[Tuple[int, int], Set[int]]


def _selectable(effective_type: str) -> bool:
    return effective_type != "NotUsable"


def _forced(effective_type: str) -> bool:
    return effective_type == "Required"


def default_selections(model: FomodModel) -> Selections:
    """The selection a wizard would start with (and the v1 'auto-apply defaults' behaviour):
    every Required/Recommended plugin, plus the minimum each group type demands. Evaluated against
    the flags produced so far, so later steps see earlier defaults."""
    sel: Selections = {}
    flags: Dict[str, str] = {}
    for si, step in enumerate(model.install_steps):
        if step.visible is not None and not step.visible.evaluate(flags):
            continue
        for gi, group in enumerate(step.groups):
            etypes = [p.type_descriptor.effective_type(flags) for p in group.plugins]
            if group.type == "SelectAll":
                chosen: Set[int] = set(range(len(group.plugins)))  # every plugin installs, no choice
            else:
                chosen = {pi for pi, et in enumerate(etypes) if _forced(et) or et == "Recommended"}
                if group.type in ("SelectExactlyOne", "SelectAtLeastOne") and not chosen:
                    first = next((pi for pi, et in enumerate(etypes) if _selectable(et)), None)
                    if first is not None:
                        chosen.add(first)
                if group.type == "SelectExactlyOne" and len(chosen) > 1:
                    chosen = {min(chosen)}
            sel[(si, gi)] = chosen
            for pi in chosen:
                for fname, fval in group.plugins[pi].condition_flags:
                    flags[fname] = fval
    return sel


# ---- resolution -------------------------------------------------------------

def _validate_group(group: Group, chosen: Set[int]) -> None:
    n = len(chosen)
    t = group.type
    if t == "SelectExactlyOne" and n != 1:
        raise FomodSelectionError("group %r requires exactly one, got %d" % (group.name, n))
    if t == "SelectAtMostOne" and n > 1:
        raise FomodSelectionError("group %r allows at most one, got %d" % (group.name, n))
    if t == "SelectAtLeastOne" and n < 1:
        raise FomodSelectionError("group %r requires at least one" % group.name)
    if t == "SelectAll" and n != len(group.plugins):
        raise FomodSelectionError("group %r requires all %d" % (group.name, len(group.plugins)))


def resolve(model: FomodModel, selections: Selections) -> InstallPlan:
    """Walk the steps in order applying `selections`, producing the ordered file operations and the
    final flag state. Required plugins are force-included and NotUsable ones dropped (per their
    flag-evaluated type) before the group constraint is checked. requiredInstallFiles and any
    matching conditionalFileInstalls are appended. Operations are returned sorted by priority
    (stable), so a consumer applying them in order gets FOMOD's last-writer-wins behaviour."""
    flags: Dict[str, str] = {}
    ops: List[FileOp] = []
    for si, step in enumerate(model.install_steps):
        if step.visible is not None and not step.visible.evaluate(flags):
            continue
        for gi, group in enumerate(step.groups):
            requested = set(selections.get((si, gi), set()))
            etypes = [p.type_descriptor.effective_type(flags) for p in group.plugins]
            chosen = {pi for pi in requested if 0 <= pi < len(group.plugins) and _selectable(etypes[pi])}
            for pi, et in enumerate(etypes):
                if _forced(et):
                    chosen.add(pi)
            _validate_group(group, chosen)
            for pi in sorted(chosen):
                ops.extend(group.plugins[pi].files)
                for fname, fval in group.plugins[pi].condition_flags:
                    flags[fname] = fval
    ops.extend(model.required_install_files)
    for cond, files in model.conditional_installs:
        if cond.evaluate(flags):
            ops.extend(files)
    ops_sorted = sorted(ops, key=lambda o: o.priority)  # stable: ties keep declaration order
    return InstallPlan(operations=ops_sorted, flags=flags)
