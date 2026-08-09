import { describe, it, expect } from 'vitest';
import { gamesNeedingReset, resetAllSummary } from './resetAll';
import type { GameStatus } from '../types';

const game = (over: Partial<GameStatus>): GameStatus => ({
  appid: 1, name: 'Game', installed: true, installed_mods: [],
  modloader_installed: false, vanilla: false,
  ...over,
}) as GameStatus;

describe('gamesNeedingReset', () => {
  it('keeps games with mods, a loader, or a vanilla-mode snapshot', () => {
    const withMods = game({ appid: 1, installed_mods: [{ id: 'm' } as any] });
    const withLoader = game({ appid: 2, modloader_installed: true });
    const inVanilla = game({ appid: 3, vanilla: true });
    const untouched = game({ appid: 4 });
    const notInstalled = game({ appid: 5, installed: false, modloader_installed: true });
    expect(gamesNeedingReset([withMods, withLoader, inVanilla, untouched, notInstalled])
      .map(g => g.appid)).toEqual([1, 2, 3]);
  });
});

describe('resetAllSummary', () => {
  it('totals games and mods on full success', () => {
    expect(resetAllSummary([
      { name: 'A', result: { ok: true, mods_removed: 3, modloader_removed: true } },
      { name: 'B', result: { ok: true, mods_removed: 1, modloader_removed: false } },
    ])).toBe('Reset 2 games — 4 mods removed');
  });

  it('singularizes correctly', () => {
    expect(resetAllSummary([
      { name: 'A', result: { ok: true, mods_removed: 1, modloader_removed: true } },
    ])).toBe('Reset 1 game — 1 mod removed');
  });

  it('names the games that failed, counting their partial removals', () => {
    expect(resetAllSummary([
      { name: 'A', result: { ok: true, mods_removed: 2, modloader_removed: true } },
      { name: 'B', result: { ok: false, mods_removed: 1, modloader_removed: false } },
      { name: 'C', result: null },
    ])).toBe('Reset 1 game — 3 mods removed; failed for B, C — check the log');
  });
});
