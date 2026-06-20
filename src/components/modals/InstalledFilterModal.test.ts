import { describe, it, expect } from 'vitest';
import { installedMatchesFilter, sortInstalledEntries, defaultInstalledFilter, InstalledFilter } from './InstalledFilterModal';
import type { ModEntry } from '../ModEntry';

// installedMatchesFilter decides whether a mod row shows under the Installed-tab filter. Three rules
// applied in order: hideLibraries, then onlyUpdates, then the enabled/disabled visibility toggles.
// (importing the modal pulls in @decky/ui, mocked in test/setup.ts.)

const entry = (
  { enabled = true, hasUpdate = false, isLibrary = false } = {},
): ModEntry => ({
  id: 'm', name: 'm', installed: true, enabled, version: '1.0', hasUpdate,
  dependenciesMet: true, isLibrary, info: {} as ModEntry['info'],
}) as ModEntry;

const filter = (over: Partial<InstalledFilter> = {}): InstalledFilter =>
  ({ enabled: true, disabled: true, onlyUpdates: false, hideLibraries: false, sortBy: 'name', ...over });

describe('installedMatchesFilter', () => {
  describe('enabled/disabled visibility', () => {
    it('shows an enabled mod only when the enabled toggle is on', () => {
      expect(installedMatchesFilter(entry({ enabled: true }), filter({ enabled: true }))).toBe(true);
      expect(installedMatchesFilter(entry({ enabled: true }), filter({ enabled: false }))).toBe(false);
    });
    it('shows a disabled mod only when the disabled toggle is on', () => {
      expect(installedMatchesFilter(entry({ enabled: false }), filter({ disabled: true }))).toBe(true);
      expect(installedMatchesFilter(entry({ enabled: false }), filter({ disabled: false }))).toBe(false);
    });
  });

  describe('hideLibraries', () => {
    it('hides a library when on', () => {
      expect(installedMatchesFilter(entry({ isLibrary: true }), filter({ hideLibraries: true }))).toBe(false);
    });
    it('shows a library when off (subject to the enabled/disabled toggles)', () => {
      expect(installedMatchesFilter(entry({ isLibrary: true }), filter({ hideLibraries: false }))).toBe(true);
    });
  });

  describe('onlyUpdates', () => {
    it('hides a mod with no update when on', () => {
      expect(installedMatchesFilter(entry({ hasUpdate: false }), filter({ onlyUpdates: true }))).toBe(false);
    });
    it('shows a mod with an update when on', () => {
      expect(installedMatchesFilter(entry({ hasUpdate: true }), filter({ onlyUpdates: true }))).toBe(true);
    });
    it('ignores updates when off', () => {
      expect(installedMatchesFilter(entry({ hasUpdate: false }), filter({ onlyUpdates: false }))).toBe(true);
    });
  });

  describe('precedence', () => {
    it('hideLibraries beats onlyUpdates (a library with an update is still hidden)', () => {
      expect(
        installedMatchesFilter(entry({ isLibrary: true, hasUpdate: true }), filter({ hideLibraries: true, onlyUpdates: true })),
      ).toBe(false);
    });
    it('onlyUpdates beats the enabled toggle (an enabled mod with no update is hidden)', () => {
      expect(
        installedMatchesFilter(entry({ enabled: true, hasUpdate: false }), filter({ enabled: true, onlyUpdates: true })),
      ).toBe(false);
    });
  });

  it('default filter hides libraries and shows enabled + disabled', () => {
    expect(defaultInstalledFilter.hideLibraries).toBe(true);
    expect(installedMatchesFilter(entry({ isLibrary: true }), defaultInstalledFilter)).toBe(false);
    expect(installedMatchesFilter(entry({ enabled: true }), defaultInstalledFilter)).toBe(true);
    expect(installedMatchesFilter(entry({ enabled: false }), defaultInstalledFilter)).toBe(true);
  });
});

// sortInstalledEntries orders the Installed-tab list. Name is the tiebreaker for every mode,
// so results stay deterministic within a group and across legacy mods with no install time.
describe('sortInstalledEntries', () => {
  const e = (
    { name = 'm', enabled = true, hasUpdate = false, addedAt = 0 } = {},
  ): ModEntry => ({
    id: name, name, installed: true, enabled, version: '1.0', hasUpdate,
    dependenciesMet: true, isLibrary: false, addedAt, info: {} as ModEntry['info'],
  }) as ModEntry;
  const names = (list: ModEntry[]) => list.map(x => x.name);

  it('sorts by name A–Z, case-insensitively', () => {
    const out = sortInstalledEntries([e({ name: 'Banana' }), e({ name: 'apple' }), e({ name: 'Cherry' })], 'name');
    expect(names(out)).toEqual(['apple', 'Banana', 'Cherry']);
  });

  it('sorts recently-downloaded newest-first, untimed mods last (by name)', () => {
    const out = sortInstalledEntries([
      e({ name: 'old', addedAt: 100 }),
      e({ name: 'new', addedAt: 200 }),
      e({ name: 'zeta', addedAt: 0 }),
      e({ name: 'alpha', addedAt: 0 }),
    ], 'recent');
    expect(names(out)).toEqual(['new', 'old', 'alpha', 'zeta']);
  });

  it('groups enabled before disabled, name as tiebreaker', () => {
    const out = sortInstalledEntries([
      e({ name: 'b', enabled: false }),
      e({ name: 'a', enabled: true }),
      e({ name: 'c', enabled: false }),
      e({ name: 'd', enabled: true }),
    ], 'enabled');
    expect(names(out)).toEqual(['a', 'd', 'b', 'c']);
  });

  it('brings mods with updates to the top, name as tiebreaker', () => {
    const out = sortInstalledEntries([
      e({ name: 'x', hasUpdate: false }),
      e({ name: 'y', hasUpdate: true }),
      e({ name: 'a', hasUpdate: false }),
    ], 'updates');
    expect(names(out)).toEqual(['y', 'a', 'x']);
  });

  it('does not mutate the input array', () => {
    const input = [e({ name: 'b' }), e({ name: 'a' })];
    const copy = [...input];
    sortInstalledEntries(input, 'name');
    expect(input).toEqual(copy);
  });

  it('falls back to name order for an unknown sort key', () => {
    const out = sortInstalledEntries([e({ name: 'b' }), e({ name: 'a' })], 'bogus' as any);
    expect(names(out)).toEqual(['a', 'b']);
  });
});
