// Pure client-side evaluation for the FOMOD install wizard. Mirrors the backend engine's flag
// semantics (fomod.py) so the wizard can show/hide steps and reflect plugin states live as the user
// chooses — without a backend round-trip per click. resolve() on the backend remains the source of
// truth; this only drives the UI. Kept dependency-free so it's unit-testable in the vitest harness.
import { FomodModel, FomodCondition, FomodPlugin } from '../types';

// Selections keyed by `${stepIdx}:${groupIdx}` -> chosen plugin indices within that group.
export type Selections = Record<string, number[]>;

export const gkey = (stepIdx: number, groupIdx: number): string => `${stepIdx}:${groupIdx}`;

export function evalCond(cond: FomodCondition | null, flags: Record<string, string>): boolean {
  if (!cond) return true;
  const results = [
    ...cond.flags.map(([f, v]) => flags[f] === v),
    ...cond.children.map(c => evalCond(c, flags)),
  ];
  if (results.length === 0) return true;
  return cond.op === 'And' ? results.every(Boolean) : results.some(Boolean);
}

// Walk steps in order: a step is visible iff its `visible` condition holds against the flags set by
// prior visible steps. Returns the visible step indices and the accumulated flag state.
export function evalWizard(model: FomodModel, sel: Selections): { visibleSteps: number[]; flags: Record<string, string> } {
  const flags: Record<string, string> = {};
  const visibleSteps: number[] = [];
  model.steps.forEach((step, si) => {
    if (step.visible && !evalCond(step.visible, flags)) return;
    visibleSteps.push(si);
    step.groups.forEach((group, gi) => {
      (sel[gkey(si, gi)] ?? []).forEach(pi => {
        group.plugins[pi]?.flags.forEach(([f, v]) => { flags[f] = v; });
      });
    });
  });
  return { visibleSteps, flags };
}

// A plugin's effective selectability state given the current flags (Optional/Required/Recommended/
// NotUsable/CouldBeUsable) — patterns (dependencyType) override the default in order.
export function effType(plugin: FomodPlugin, flags: Record<string, string>): string {
  for (const pat of plugin.type.patterns) if (evalCond(pat.cond, flags)) return pat.type;
  return plugin.type.default;
}

export function defaultSelections(model: FomodModel): Selections {
  const sel: Selections = {};
  for (const [si, gi, plugins] of model.default) sel[gkey(si, gi)] = [...plugins];
  return sel;
}

// Encode for the backend resume channel: [[stepIdx, groupIdx, [pluginIdx, ...]], ...].
export function encodeSelections(sel: Selections): [number, number, number[]][] {
  return Object.entries(sel).map(([k, plugins]) => {
    const [si, gi] = k.split(':').map(Number);
    return [si, gi, [...plugins].sort((a, b) => a - b)] as [number, number, number[]];
  });
}

function normalizeOnce(model: FomodModel, sel: Selections): Selections {
  const { visibleSteps, flags } = evalWizard(model, sel);
  let next = sel;
  const ensure = (key: string, value: number[]) => {
    const a = [...value].sort((x, y) => x - y);
    const prev = [...(sel[key] ?? [])].sort((x, y) => x - y);
    if (JSON.stringify(a) !== JSON.stringify(prev)) {
      if (next === sel) next = { ...sel };
      next[key] = a;
    }
  };
  for (const si of visibleSteps) {
    model.steps[si].groups.forEach((group, gi) => {
      const usable = group.plugins.map((p, pi) => ({ pi, t: effType(p, flags) })).filter(x => x.t !== 'NotUsable');
      const usableIdx = new Set(usable.map(u => u.pi));
      const required = usable.filter(u => u.t === 'Required').map(u => u.pi);
      let picked = (sel[gkey(si, gi)] ?? []).filter(pi => usableIdx.has(pi));  // drop NotUsable/stale
      if (group.type === 'SelectAll') {
        picked = usable.map(u => u.pi);
      } else if (group.type === 'SelectExactlyOne') {
        if (picked.length !== 1) {
          const pick = usable.find(u => u.t === 'Recommended') ?? usable.find(u => u.t === 'Required') ?? usable[0];
          picked = pick ? [pick.pi] : [];
        }
      } else if (group.type === 'SelectAtLeastOne') {
        picked = Array.from(new Set([...picked, ...required]));
        if (picked.length === 0 && usable[0]) picked = [usable[0].pi];
      } else { // SelectAny / SelectAtMostOne
        picked = Array.from(new Set([...picked, ...required]));
        if (group.type === 'SelectAtMostOne' && picked.length > 1) picked = [picked[0]];
      }
      ensure(gkey(si, gi), picked);
    });
  }
  return next;
}

// Fill in the implied selection for every VISIBLE group (a pick-one with no/invalid choice gets its
// recommended/first option; a SelectAll gets everything; Required plugins are forced in; NotUsable
// ones dropped). Iterated to a fixpoint because filling one group's default can set a flag that
// reveals another step. Keeps the wizard's state consistent with what the controls display — so a
// step revealed by a choice doesn't leave the Install button disabled on an "empty" group.
export function normalize(model: FomodModel, sel: Selections): Selections {
  let cur = sel;
  for (let i = 0; i <= model.steps.length + 1; i++) {
    const next = normalizeOnce(model, cur);
    if (next === cur) return cur;  // stable (same ref) — done
    cur = next;
  }
  return cur;
}

// Whether every VISIBLE group satisfies its constraint — gates the Install button so we never send
// the backend a selection resolve() would reject (e.g. an empty SelectAtLeastOne).
export function isComplete(model: FomodModel, sel: Selections): boolean {
  const { visibleSteps, flags } = evalWizard(model, sel);
  for (const si of visibleSteps) {
    const step = model.steps[si];
    for (let gi = 0; gi < step.groups.length; gi++) {
      const group = step.groups[gi];
      // count selected (non-NotUsable) plus any Required plugin — the backend force-includes those.
      const picked = sel[gkey(si, gi)] ?? [];
      const n = group.plugins.reduce((acc, p, pi) => {
        const t = effType(p, flags);
        return acc + (t !== 'NotUsable' && (picked.includes(pi) || t === 'Required') ? 1 : 0);
      }, 0);
      if (group.type === 'SelectExactlyOne' && n !== 1) return false;
      if (group.type === 'SelectAtLeastOne' && n < 1) return false;
    }
  }
  return true;
}
