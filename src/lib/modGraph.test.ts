import { describe, it, expect } from 'vitest';
import { buildModGraph, stripVersion } from './modGraph';
import type { InstalledMod } from '../types';

// Build an installed mod with the fields the graph reads (id, enabled, meta.dependencies).
const mod = (id: string, deps: string[] = [], enabled = true): InstalledMod => ({
  id, filename: id, enabled, version: '1.0.0', is_library: false,
  meta: { name: id, author: '', description: '', homepage: '', thumbnail: '', modloader: '', dependencies: deps },
}) as InstalledMod;

describe('stripVersion', () => {
  it('drops the trailing version segment', () => {
    expect(stripVersion('Owner-Mod-1.2.3')).toBe('Owner-Mod');
    expect(stripVersion('FunkFrog-and-Sipondo-ShareSuite-2.5.1')).toBe('FunkFrog-and-Sipondo-ShareSuite');
  });
  it('yields "" for a hyphen-free id (no version to strip)', () => {
    expect(stripVersion('workshop.480.123')).toBe('');
  });
});

describe('resolveDepId', () => {
  it('strips the version off a Thunderstore dep string', () => {
    const g = buildModGraph([mod('OwnerB-ModB')], new Set());
    expect(g.resolveDepId('OwnerB-ModB-1.2.3')).toBe('ownerb-modb');
  });
  it('prefers a direct installed-id match over stripping (avoids mangling hyphenated ids)', () => {
    // 'Owner-Mod' installed: a dep "Owner-Mod" must resolve to itself, NOT be stripped to 'owner'.
    const g = buildModGraph([mod('Owner-Mod')], new Set());
    expect(g.resolveDepId('Owner-Mod')).toBe('owner-mod');
  });
  it('falls back to the raw id for a hyphen-free dep with no version to strip', () => {
    const g = buildModGraph([], new Set());
    expect(g.resolveDepId('workshop.480.123')).toBe('workshop.480.123');
  });
});

describe('modDeps', () => {
  it('resolves declared deps and drops denylisted (modloader-provided) packages', () => {
    const a = mod('Owner-A', ['OwnerB-ModB-1.0.0', 'BepInEx-BepInExPack-5.4.0']);
    const g = buildModGraph([a, mod('OwnerB-ModB')], new Set(['bepinex-bepinexpack']));
    expect(g.modDeps(a)).toEqual(['ownerb-modb']);
  });
  it('returns [] for a mod with no meta/deps', () => {
    const g = buildModGraph([], new Set());
    expect(g.modDeps(null)).toEqual([]);
  });
});

describe('collectEnableDeps', () => {
  it('collects transitive disabled deps (A -> B -> C)', () => {
    const g = buildModGraph([
      mod('A', ['B-1.0.0'], true),
      mod('B', ['C-1.0.0'], false),
      mod('C', [], false),
    ], new Set());
    const { missing, disabled } = g.collectEnableDeps(['A']);
    expect(missing).toEqual([]);
    expect([...disabled].sort()).toEqual(['b', 'c']);
  });

  it('reports a not-installed dependency as missing', () => {
    const g = buildModGraph([mod('A', ['Missing-Dep-1.0.0'], true)], new Set());
    const { missing, disabled } = g.collectEnableDeps(['A']);
    expect(disabled).toEqual([]);
    expect(missing).toEqual(['missing-dep']);
  });

  it('walks through an already-enabled dep to find a disabled sub-dep', () => {
    const g = buildModGraph([
      mod('A', ['B-1.0.0'], true),
      mod('B', ['C-1.0.0'], true), // enabled — but its sub-dep is off
      mod('C', [], false),
    ], new Set());
    expect(g.collectEnableDeps(['A']).disabled).toEqual(['c']);
  });

  it('is cycle-safe (B <-> C)', () => {
    const g = buildModGraph([
      mod('A', ['B-1.0.0'], true),
      mod('B', ['C-1.0.0'], false),
      mod('C', ['B-1.0.0'], false),
    ], new Set());
    expect(() => g.collectEnableDeps(['A'])).not.toThrow();
    expect([...g.collectEnableDeps(['A']).disabled].sort()).toEqual(['b', 'c']);
  });
});

describe('collectDependents', () => {
  // Y depends on X, X depends on A. Y is disabled.
  const graphMods = [mod('A', [], true), mod('X', ['A-1.0.0'], true), mod('Y', ['X-1.0.0'], false)];

  it('collects transitive dependents (reverse of the enable walk)', () => {
    const g = buildModGraph(graphMods, new Set());
    expect(g.collectDependents(['A'], false).map(m => m.id).sort()).toEqual(['X', 'Y']);
  });

  it('with requireEnabled, stops at a disabled dependent', () => {
    const g = buildModGraph(graphMods, new Set());
    // X is enabled → followed; Y is disabled → neither counted nor traversed.
    expect(g.collectDependents(['A'], true).map(m => m.id)).toEqual(['X']);
  });

  it('excludes the roots themselves', () => {
    const g = buildModGraph(graphMods, new Set());
    expect(g.collectDependents(['A', 'X'], false).map(m => m.id)).toEqual(['Y']);
  });
});

describe('topoEnableOrder', () => {
  it('orders each mod after its in-set dependencies (A -> B -> C => C, B, A)', () => {
    const g = buildModGraph([
      mod('A', ['B-1.0.0']),
      mod('B', ['C-1.0.0']),
      mod('C', []),
    ], new Set());
    expect(g.topoEnableOrder(['A', 'B', 'C'])).toEqual(['C', 'B', 'A']);
  });

  it('ignores dependencies outside the id set', () => {
    const g = buildModGraph([mod('A', ['B-1.0.0']), mod('B', [])], new Set());
    expect(g.topoEnableOrder(['A'])).toEqual(['A']);
  });
});
