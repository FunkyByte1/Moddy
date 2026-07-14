import { describe, it, expect } from 'vitest';
import { catalogItem, catalogDetail, filterCatalog, catalogCategories } from './catalogAdapter';
import type { ThunderstorePackage } from '../../types';

// The Thunderstore/BMI adapters' pure helpers: normalize the catalog payload and reproduce
// BrowseTab's client-side filter/sort/category pipeline. (Importing the adapter pulls in @decky,
// mocked in vitest-setup/setup.ts.)

const pkg = (
  over: Partial<ThunderstorePackage> & { description?: string; deps?: string[]; version?: string } = {},
): ThunderstorePackage => {
  const { description, deps, version, ...rest } = over;
  return {
    full_name: 'Owner-Mod', name: 'Mod', owner: 'Owner', date_updated: '2025-03-04T00:00:00Z',
    rating_score: 10, is_deprecated: false, has_nsfw_content: false, categories: ['Tweaks'],
    latest: { icon: 'http://icon', version_number: version ?? '1.2.3', description: description ?? 'desc', dependencies: deps ?? [] },
    ...rest,
  } as unknown as ThunderstorePackage;
};

describe('catalogItem', () => {
  it('normalizes the package (installId lowercased)', () => {
    expect(catalogItem(pkg(), new Set())).toEqual({
      key: 'Owner-Mod', installId: 'owner-mod', title: 'Mod', subtitle: 'Owner',
      iconUrl: 'http://icon', isLibrary: false, raw: pkg(),
    });
  });
  it('flags isLibrary when a category is in the library set', () => {
    expect(catalogItem(pkg({ categories: ['Libraries'] }), new Set(['libraries'])).isLibrary).toBe(true);
    expect(catalogItem(pkg({ categories: ['Tweaks'] }), new Set(['libraries'])).isLibrary).toBe(false);
  });
});

describe('catalogDetail', () => {
  it('shows likes when rating_score > 0, categories as tags, deprecated flag', () => {
    const d = catalogDetail(pkg({ categories: ['Tweaks', 'Audio'], is_deprecated: true }));
    expect(d.byline).toBe('by Owner · v1.2.3 · 10 likes');
    expect(d.tags).toEqual(['Tweaks', 'Audio']);
    expect(d.deprecated).toBe(true);
    expect(d.description).toBe('desc');
  });
  it('falls back to updated date when rating_score is 0', () => {
    expect(catalogDetail(pkg({ rating_score: 0 })).byline).toBe('by Owner · v1.2.3 · updated 2025-03-04');
  });
});

describe('filterCatalog', () => {
  const A = pkg({ full_name: 'O-A', name: 'Apple', rating_score: 5, date_updated: '2025-01-01', categories: ['Tweaks'], description: 'alpha tool' });
  const B = pkg({ full_name: 'O-B', name: 'Mango', rating_score: 9, date_updated: '2023-01-01', categories: ['Audio'], description: 'beta tool' });
  const C = pkg({ full_name: 'O-C', name: 'Zebra', rating_score: 1, date_updated: '2024-01-01', categories: ['Tweaks', 'Audio'], description: 'gamma' });
  const catalog = [A, B, C];
  const names = (l: ThunderstorePackage[]) => l.map(p => p.full_name);

  it('drops denylisted packages', () => {
    expect(names(filterCatalog(catalog, new Set(['o-b']), ''))).toEqual(['O-A', 'O-C']); // rating sort: A(5), C(1)
  });
  it('drops real modpacks (Modpacks category + an installable dep), even if dual-tagged Mods', () => {
    const pack = pkg({ full_name: 'O-Pack', categories: ['Mods', 'Modpacks'], deps: ['Some-RealMod-1.0.0'] });
    expect(names(filterCatalog([...catalog, pack], new Set(), ''))).toEqual(['O-B', 'O-A', 'O-C']); // O-Pack excluded
  });
  it('keeps a Modpacks-tagged package whose only dep is the (denylisted) loader — it is a mis-tagged content mod', () => {
    const fake = pkg({ full_name: 'O-Fake', name: 'Fake', categories: ['Mods', 'Modpacks'], deps: ['BepInEx-BepInExPack-5.0.0'] });
    const out = names(filterCatalog([...catalog, fake], new Set(['bepinex-bepinexpack']), ''));
    expect(out).toContain('O-Fake'); // shown in Browse as a normal mod
  });
  it('hides deprecated/nsfw unless explicitly shown', () => {
    const dep = pkg({ full_name: 'O-D', is_deprecated: true });
    const nsfw = pkg({ full_name: 'O-N', has_nsfw_content: true });
    expect(names(filterCatalog([dep, nsfw], new Set(), '')).length).toBe(0);
    expect(names(filterCatalog([dep], new Set(), '', { installed: true, notInstalled: true, showNsfw: false, showDeprecated: true }))).toEqual(['O-D']);
    expect(names(filterCatalog([nsfw], new Set(), '', { installed: true, notInstalled: true, showNsfw: true }))).toEqual(['O-N']);
  });
  it('filters by category intersection', () => {
    expect(new Set(names(filterCatalog(catalog, new Set(), '', { installed: true, notInstalled: true, showNsfw: false, categories: ['Audio'] }))))
      .toEqual(new Set(['O-B', 'O-C']));
  });
  it('searches over full_name and description', () => {
    expect(names(filterCatalog(catalog, new Set(), 'gamma'))).toEqual(['O-C']);
    expect(names(filterCatalog(catalog, new Set(), 'tool')).sort()).toEqual(['O-A', 'O-B']);
  });
  it('sorts by rating (default), name, and updated — each distinct', () => {
    expect(names(filterCatalog(catalog, new Set(), ''))).toEqual(['O-B', 'O-A', 'O-C']);                              // rating desc
    expect(names(filterCatalog(catalog, new Set(), '', { installed: true, notInstalled: true, showNsfw: false, sortBy: 'name' }))).toEqual(['O-A', 'O-B', 'O-C']);    // name asc
    expect(names(filterCatalog(catalog, new Set(), '', { installed: true, notInstalled: true, showNsfw: false, sortBy: 'updated' }))).toEqual(['O-A', 'O-C', 'O-B']); // updated desc
  });
  it('does NOT apply hide-libraries / install-status (those are pagedVisible\'s job)', () => {
    // hideLibraries set, but filterCatalog returns everything — the component's pagedVisible drops libs.
    expect(names(filterCatalog(catalog, new Set(), '', { installed: true, notInstalled: true, showNsfw: false, hideLibraries: true })).sort())
      .toEqual(['O-A', 'O-B', 'O-C']);
  });
});

describe('catalogCategories', () => {
  it('returns sorted, deduped, non-library categories from non-denylisted packages', () => {
    const catalog = [
      pkg({ full_name: 'O-A', categories: ['Tweaks', 'Audio'] }),
      pkg({ full_name: 'O-B', categories: ['Audio', 'Libraries'] }),
      pkg({ full_name: 'O-Deny', categories: ['Secret'] }),
    ];
    expect(catalogCategories(catalog, new Set(['o-deny']), new Set(['libraries'])))
      .toEqual(['Audio', 'Tweaks']); // 'Libraries' excluded (library), 'Secret' excluded (denylisted), deduped + sorted
  });
  it('does not offer Modpacks as a filter category (real modpacks are excluded from the mods list)', () => {
    const catalog = [
      pkg({ full_name: 'O-A', categories: ['Tweaks'] }),
      pkg({ full_name: 'O-Pack', categories: ['Mods', 'Modpacks'], deps: ['Some-RealMod-1.0.0'] }),
    ];
    expect(catalogCategories(catalog, new Set(), new Set(['libraries']))).toEqual(['Tweaks']);
  });
});
