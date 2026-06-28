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
