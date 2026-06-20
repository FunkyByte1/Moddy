import { describe, it, expect } from 'vitest';
import { transitiveCatalogDeps } from './browseDeps';
import type { ThunderstorePackage } from './types';

// transitiveCatalogDeps walks the catalog dependency tree from a set of root refs. BrowseTab uses it
// over in-flight installs so it doesn't re-prompt for deps already being installed (the recursive
// walk is the fix for transitively-shared deps).

const pkg = (full_name: string, deps: string[] = []): ThunderstorePackage =>
  ({ full_name, latest: { dependencies: deps } } as unknown as ThunderstorePackage);

describe('transitiveCatalogDeps', () => {
  it('includes the roots and their direct deps', () => {
    const catalog = [pkg('Owner-A', ['Owner-B-1.0.0']), pkg('Owner-B')];
    expect(transitiveCatalogDeps(catalog, ['Owner-A'])).toEqual(new Set(['owner-a', 'owner-b']));
  });

  it('walks the full transitive tree (A -> B -> C)', () => {
    const catalog = [pkg('Owner-A', ['Owner-B-1.0.0']), pkg('Owner-B', ['Owner-C-1.0.0']), pkg('Owner-C')];
    expect(transitiveCatalogDeps(catalog, ['Owner-A'])).toEqual(new Set(['owner-a', 'owner-b', 'owner-c']));
  });

  it('covers a transitively-pulled dep (the case a non-recursive walk missed)', () => {
    // A reaches C only through B; a second mod that declares C directly should see it as covered.
    const catalog = [pkg('Owner-A', ['Owner-B-1.0.0']), pkg('Owner-B', ['Owner-C-1.0.0']), pkg('Owner-C')];
    expect(transitiveCatalogDeps(catalog, ['Owner-A']).has('owner-c')).toBe(true);
  });

  it('strips version suffixes, including hyphenated owner/package names', () => {
    const catalog = [
      pkg('Me-Mod', ['FunkFrog-and-Sipondo-ShareSuite-2.5.1']),
      pkg('FunkFrog-and-Sipondo-ShareSuite'),
    ];
    expect(transitiveCatalogDeps(catalog, ['Me-Mod']))
      .toEqual(new Set(['me-mod', 'funkfrog-and-sipondo-sharesuite']));
  });

  it('records a dependency not in the catalog without recursing', () => {
    const catalog = [pkg('Owner-A', ['Ghost-Dep-1.0.0'])];
    expect(transitiveCatalogDeps(catalog, ['Owner-A'])).toEqual(new Set(['owner-a', 'ghost-dep']));
  });

  it('is cycle-safe (A <-> B)', () => {
    const catalog = [pkg('Owner-A', ['Owner-B-1.0.0']), pkg('Owner-B', ['Owner-A-1.0.0'])];
    expect(() => transitiveCatalogDeps(catalog, ['Owner-A'])).not.toThrow();
    expect(transitiveCatalogDeps(catalog, ['Owner-A'])).toEqual(new Set(['owner-a', 'owner-b']));
  });

  it('handles multiple roots and dedups a shared dependency', () => {
    const catalog = [
      pkg('Owner-A', ['Shared-Lib-1.0.0']),
      pkg('Owner-B', ['Shared-Lib-1.0.0']),
      pkg('Shared-Lib'),
    ];
    expect(transitiveCatalogDeps(catalog, ['Owner-A', 'Owner-B']))
      .toEqual(new Set(['owner-a', 'owner-b', 'shared-lib']));
  });

  it('returns an empty set for no roots', () => {
    expect(transitiveCatalogDeps([pkg('Owner-A')], [])).toEqual(new Set());
  });
});
