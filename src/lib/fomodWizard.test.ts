import { describe, it, expect } from 'vitest';
import {
  evalCond, evalWizard, effType, defaultSelections, encodeSelections, isComplete, gkey, Selections,
} from './fomodWizard';
import type { FomodModel, FomodPlugin } from '../types';

const plugin = (name: string, over: Partial<FomodPlugin> = {}): FomodPlugin => ({
  name, description: '', image: null, flags: [], type: { default: 'Optional', patterns: [] }, ...over,
});

// step 1: pick A (sets flag picked=A) or B; step 2: visible only if picked=A, one required plugin.
const model: FomodModel = {
  moduleName: 'M',
  steps: [
    {
      name: 'S1', visible: null,
      groups: [{
        name: 'Pick', type: 'SelectExactlyOne',
        plugins: [plugin('A', { flags: [['picked', 'A']] }), plugin('B')],
      }],
    },
    {
      name: 'S2',
      visible: { op: 'And', flags: [['picked', 'A']], children: [] },
      groups: [{ name: 'Extra', type: 'SelectAll', plugins: [plugin('E', { type: { default: 'Required', patterns: [] } })] }],
    },
  ],
  default: [[0, 0, [0]], [1, 0, [0]]],
};

describe('evalCond', () => {
  it('empty condition is true; And/Or over flags', () => {
    expect(evalCond(null, {})).toBe(true);
    expect(evalCond({ op: 'And', flags: [['x', 'On']], children: [] }, { x: 'On' })).toBe(true);
    expect(evalCond({ op: 'And', flags: [['x', 'On']], children: [] }, {})).toBe(false);
    expect(evalCond({ op: 'Or', flags: [['x', 'On'], ['y', 'On']], children: [] }, { y: 'On' })).toBe(true);
  });
});

describe('evalWizard visibility', () => {
  it('step 2 hidden until step 1 sets the flag', () => {
    const pickB: Selections = { [gkey(0, 0)]: [1] };
    expect(evalWizard(model, pickB).visibleSteps).toEqual([0]);
    const pickA: Selections = { [gkey(0, 0)]: [0] };
    expect(evalWizard(model, pickA).visibleSteps).toEqual([0, 1]);
    expect(evalWizard(model, pickA).flags).toEqual({ picked: 'A' });
  });
});

describe('effType', () => {
  it('patterns override default by flags', () => {
    const p = plugin('P', { type: { default: 'Optional', patterns: [{ cond: { op: 'And', flags: [['x', 'On']], children: [] }, type: 'Recommended' }] } });
    expect(effType(p, {})).toBe('Optional');
    expect(effType(p, { x: 'On' })).toBe('Recommended');
  });
});

describe('defaults + encode', () => {
  it('defaultSelections maps the dto; encode round-trips', () => {
    expect(defaultSelections(model)).toEqual({ [gkey(0, 0)]: [0], [gkey(1, 0)]: [0] });
    const enc = encodeSelections({ [gkey(0, 0)]: [1], [gkey(2, 1)]: [3, 0] });
    expect(enc).toContainEqual([0, 0, [1]]);
    expect(enc).toContainEqual([2, 1, [0, 3]]);
  });
});

describe('isComplete', () => {
  it('SelectExactlyOne needs exactly one (in a visible step)', () => {
    expect(isComplete(model, { [gkey(0, 0)]: [0] })).toBe(true);
    expect(isComplete(model, { [gkey(0, 0)]: [] })).toBe(false);   // empty pick-one
    expect(isComplete(model, { [gkey(0, 0)]: [0, 1] })).toBe(false); // two in pick-one
  });
  it('ignores groups in hidden steps', () => {
    // pick B -> step 2 hidden, so its SelectAtLeastOne-ness can't block completion
    const m2: FomodModel = JSON.parse(JSON.stringify(model));
    m2.steps[1].groups[0].type = 'SelectAtLeastOne';
    m2.steps[1].groups[0].plugins[0].type = { default: 'Optional', patterns: [] };
    expect(isComplete(m2, { [gkey(0, 0)]: [1], [gkey(1, 0)]: [] })).toBe(true);
  });
  it('a Required plugin satisfies its group even if not explicitly selected', () => {
    expect(isComplete(model, { [gkey(0, 0)]: [0], [gkey(1, 0)]: [] })).toBe(true); // E is Required
  });
});
