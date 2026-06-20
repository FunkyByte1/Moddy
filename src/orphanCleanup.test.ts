import { describe, it, expect } from 'vitest';
import { findOrphanedLibraries } from './orphanCleanup';
import type { GameStatus, InstalledMod } from './types';

// findOrphanedLibraries answers: "if I remove these mods, which LIBRARY mods are stranded?" —
// libraries that were depended on, whose remaining dependents are all being removed too (cascading),
// while leaving pre-existing/never-used orphans alone. importing orphanCleanup.tsx pulls in @decky/ui
// (mocked in test/setup.ts).

const mod = (
  id: string,
  { deps = [], enabled = true, library = false }: { deps?: string[]; enabled?: boolean; library?: boolean } = {},
): InstalledMod => ({
  id, filename: id, enabled, version: '1.0.0', is_library: library,
  meta: { name: id, author: '', description: '', homepage: '', thumbnail: '', modloader: '', dependencies: deps },
}) as InstalledMod;

const game = (...mods: InstalledMod[]): GameStatus => ({ appid: 1, installed_mods: mods } as GameStatus);
const ids = (mods: InstalledMod[]) => mods.map(m => m.id).sort();

describe('findOrphanedLibraries', () => {
  it('orphans a library whose only dependent is being removed', () => {
    const g = game(mod('A', { deps: ['Lib-1.0.0'] }), mod('Lib', { library: true }));
    expect(ids(findOrphanedLibraries(g, new Set(), ['A'], 'uninstall'))).toEqual(['Lib']);
  });

  it('keeps a library that still has another dependent', () => {
    const g = game(
      mod('A', { deps: ['Lib-1.0.0'] }),
      mod('B', { deps: ['Lib-1.0.0'] }),
      mod('Lib', { library: true }),
    );
    expect(findOrphanedLibraries(g, new Set(), ['A'], 'uninstall')).toEqual([]); // B still needs Lib
  });

  it('cascades through a dependency chain (Mod -> R2API -> HookGenPatcher)', () => {
    const g = game(
      mod('Mod', { deps: ['R2API-1.0.0'] }),
      mod('R2API', { deps: ['HookGenPatcher-1.0.0'], library: true }),
      mod('HookGenPatcher', { library: true }),
    );
    // Removing Mod strands R2API, which in turn strands HookGenPatcher.
    expect(ids(findOrphanedLibraries(g, new Set(), ['Mod'], 'uninstall'))).toEqual(['HookGenPatcher', 'R2API']);
  });

  it('leaves a pre-existing orphan (a library nothing ever depended on) alone', () => {
    const g = game(mod('A'), mod('Lib', { library: true })); // nothing depends on Lib
    expect(findOrphanedLibraries(g, new Set(), ['A'], 'uninstall')).toEqual([]);
  });

  it('does not flag a now-unused NON-library mod', () => {
    const g = game(mod('A', { deps: ['Plugin-1.0.0'] }), mod('Plugin', { library: false }));
    expect(findOrphanedLibraries(g, new Set(), ['A'], 'uninstall')).toEqual([]);
  });

  it('does not return the removed mod itself even if it is a library', () => {
    const g = game(mod('A', { deps: ['Lib-1.0.0'] }), mod('Lib', { library: true }));
    // Removing Lib directly: it is the removal target, not an orphan it created.
    expect(findOrphanedLibraries(g, new Set(), ['Lib'], 'uninstall')).toEqual([]);
  });

  describe('uninstall vs disable mode', () => {
    // Lib is depended on by A (enabled) and B (disabled). We remove A.
    const g = game(
      mod('Lib', { library: true, enabled: true }),
      mod('A', { deps: ['Lib-1.0.0'], enabled: true }),
      mod('B', { deps: ['Lib-1.0.0'], enabled: false }),
    );

    it('uninstall mode counts the disabled dependent, so Lib survives', () => {
      // B is still installed and depends on Lib → not orphaned.
      expect(findOrphanedLibraries(g, new Set(), ['A'], 'uninstall')).toEqual([]);
    });

    it('disable mode ignores the disabled dependent, so Lib is orphaned', () => {
      // Only enabled mods count as active dependents; B (disabled) doesn't keep Lib alive.
      expect(ids(findOrphanedLibraries(g, new Set(), ['A'], 'disable'))).toEqual(['Lib']);
    });
  });
});
