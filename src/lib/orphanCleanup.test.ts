import { describe, it, expect } from 'vitest';
import { findUnusedLibraries } from './orphanCleanup';
import type { GameStatus, InstalledMod } from '../types';

// findUnusedLibraries answers: "which LIBRARY mods does nothing installed rely on right now?" — the
// input for the Installed tab's cleanup chip. A library is used if some non-library mod (or another
// used library, transitively) depends on it; everything else is unused, including libraries nothing
// ever depended on. Disabled mods still count as consumers. Importing orphanCleanup.tsx pulls in
// @decky/ui (mocked in vitest-setup/setup.ts).

const mod = (
  id: string,
  { deps = [], enabled = true, library = false }: { deps?: string[]; enabled?: boolean; library?: boolean } = {},
): InstalledMod => ({
  id, filename: id, enabled, version: '1.0.0', is_library: library,
  meta: { name: id, author: '', description: '', homepage: '', thumbnail: '', modloader: '', dependencies: deps },
}) as InstalledMod;

const game = (...mods: InstalledMod[]): GameStatus => ({ appid: 1, installed_mods: mods } as GameStatus);
const ids = (mods: InstalledMod[]) => mods.map(m => m.id).sort();

describe('findUnusedLibraries', () => {
  it('flags a library nothing depends on', () => {
    const g = game(mod('A'), mod('Lib', { library: true }));
    expect(ids(findUnusedLibraries(g, new Set()))).toEqual(['Lib']);
  });

  it('keeps a library a non-library mod depends on', () => {
    const g = game(mod('A', { deps: ['Lib-1.0.0'] }), mod('Lib', { library: true }));
    expect(findUnusedLibraries(g, new Set())).toEqual([]);
  });

  it('keeps a library a disabled mod still depends on', () => {
    const g = game(mod('A', { deps: ['Lib-1.0.0'], enabled: false }), mod('Lib', { library: true }));
    expect(findUnusedLibraries(g, new Set())).toEqual([]); // A would want Lib back when re-enabled
  });

  it('never flags a non-library mod, even if nothing depends on it', () => {
    const g = game(mod('A', { deps: ['Plugin-1.0.0'] }), mod('Plugin', { library: false }));
    expect(findUnusedLibraries(g, new Set())).toEqual([]);
  });

  it('keeps a whole live chain (Mod -> R2API -> HookGenPatcher)', () => {
    const g = game(
      mod('Mod', { deps: ['R2API-1.0.0'] }),
      mod('R2API', { deps: ['HookGenPatcher-1.0.0'], library: true }),
      mod('HookGenPatcher', { library: true }),
    );
    expect(findUnusedLibraries(g, new Set())).toEqual([]);
  });

  it('flags a whole chain whose only non-library consumer is gone', () => {
    // No non-library mod depends on R2API → it and its sub-library are both unused.
    const g = game(
      mod('R2API', { deps: ['HookGenPatcher-1.0.0'], library: true }),
      mod('HookGenPatcher', { library: true }),
    );
    expect(ids(findUnusedLibraries(g, new Set()))).toEqual(['HookGenPatcher', 'R2API']);
  });

  it('never flags a denylisted (modloader-provided) package as unused', () => {
    // BepInExPack is core infra installed via the Mod Loader tab; edges to it are dropped from the
    // graph (not a plugin dep), so it would otherwise look dependent-less. It must never be offered.
    const g = game(mod('A', { deps: ['BepInExPack-5.4.0'] }), mod('BepInExPack', { library: true }));
    expect(findUnusedLibraries(g, new Set(['bepinexpack']))).toEqual([]);
  });
});
