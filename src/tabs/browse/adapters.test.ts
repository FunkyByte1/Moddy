import { describe, it, expect } from 'vitest';
import { nexusItem, nexusDetail } from './nexusAdapter';
import { ficsitItem, ficsitDetail } from './ficsitAdapter';
import { workshopItem, workshopDetail, fmtSubs } from './workshopAdapter';
import { collectionBrowseItem, collectionsAdapter } from './collectionsAdapter';
import { collectionsAdapterFor, venueHasCollections } from './collectionVenues';
import type { ThunderstorePackage, WorkshopCatalogItem, CollectionItem, GameStatus } from '../../types';

// The adapters' pure mappers normalize each venue's payload into the shared BrowseItem/BrowseDetail.
// (importing the adapters pulls in @decky, mocked in vitest-setup/setup.ts.)

const tsPkg = (over: Partial<ThunderstorePackage> = {}): ThunderstorePackage => ({
  full_name: 'Owner-Mod', name: 'Mod', owner: 'Owner', date_updated: '2025-03-04T00:00:00Z',
  latest: { icon: 'http://icon', version_number: '1.2.3', description: 'desc' },
  ...over,
} as unknown as ThunderstorePackage);

const wsItem = (over: Partial<WorkshopCatalogItem> = {}): WorkshopCatalogItem => ({
  id: '12345', name: 'Cool Map', preview_url: 'http://preview', subscriptions: 1500,
  description: 'a [b]bold[/b] map', tags: ['Maps', 'Co-op'], time_updated: 1700000000,
  ...over,
} as unknown as WorkshopCatalogItem);

describe('nexus adapter mappers', () => {
  it('nexusItem normalizes the package (installId lowercased)', () => {
    expect(nexusItem(tsPkg())).toEqual({
      key: 'Owner-Mod', installId: 'owner-mod', title: 'Mod', subtitle: 'Owner',
      iconUrl: 'http://icon', isLibrary: false, raw: tsPkg(),
    });
  });
  it('nexusItem carries the backend-stamped is_library flag', () => {
    expect(nexusItem(tsPkg({ is_library: true })).isLibrary).toBe(true);
    expect(nexusItem(tsPkg()).isLibrary).toBe(false);
  });
  it('nexusDetail builds the byline with version + date and no tags', () => {
    const d = nexusDetail(tsPkg());
    expect(d.byline).toBe('by Owner · v1.2.3 · updated 2025-03-04');
    expect(d.tags).toEqual([]);
    expect(d.description).toBe('desc');
  });
  it('nexusDetail omits version/date when absent', () => {
    expect(nexusDetail(tsPkg({ date_updated: '', latest: { icon: '', version_number: '', description: 'd' } } as any)).byline)
      .toBe('by Owner');
  });
});

describe('ficsit adapter mappers', () => {
  const fic = (over: Partial<ThunderstorePackage> = {}): ThunderstorePackage =>
    tsPkg({ full_name: 'ficsit.RefinedPower', name: 'Refined Power', owner: 'mrhid6', ...over });
  it('ficsitItem normalizes the package (installId lowercased)', () => {
    expect(ficsitItem(fic())).toEqual({
      key: 'ficsit.RefinedPower', installId: 'ficsit.refinedpower', title: 'Refined Power',
      subtitle: 'mrhid6', iconUrl: 'http://icon', isLibrary: false, raw: fic(),
    });
  });
  it('ficsitDetail builds the byline with version + date', () => {
    expect(ficsitDetail(fic()).byline).toBe('by mrhid6 · v1.2.3 · updated 2025-03-04');
  });
});

describe('workshop adapter mappers', () => {
  it('fmtSubs abbreviates thousands', () => {
    expect(fmtSubs(500)).toBe('500');
    expect(fmtSubs(1500)).toBe('1.5k');
    expect(fmtSubs(12000)).toBe('12k');
  });
  it('workshopItem normalizes the item (key/installId = fileId, subtitle = subs)', () => {
    expect(workshopItem(wsItem())).toEqual({
      key: '12345', installId: '12345', title: 'Cool Map', subtitle: '1.5k subscribers',
      iconUrl: 'http://preview', raw: wsItem(),
    });
  });
  it('workshopDetail strips BBCode from the description and surfaces tags', () => {
    const d = workshopDetail(wsItem());
    expect(d.description).toBe('a bold map');
    expect(d.tags).toEqual(['Maps', 'Co-op']);
    expect(d.byline).toBe('1.5k subscribers · updated 2023-11-14');
  });
});

const coll = (over: Partial<CollectionItem> = {}): CollectionItem => ({
  slug: 'vmu2j4', name: 'Worldly Improvements', author: 'Kap', summary: 'better world',
  mod_count: 5, endorsements: 42, tile_image: 'http://tile', ...over,
});

describe('collectionsAdapter', () => {
  it('maps a collection to a browse item keyed for the queue job ref', () => {
    const it0 = collectionBrowseItem(coll());
    // key/installId must mirror the backend job ref `collection:<slug>` so the busy mark hands off.
    expect(it0.key).toBe('collection:vmu2j4');
    expect(it0.installId).toBe('collection:vmu2j4');
    expect(it0.title).toBe('Worldly Improvements');
    expect(it0.subtitle).toBe('by Kap · 5 mods');
    expect(it0.iconUrl).toBe('http://tile');
  });
  it('detail bylines mods + endorsements', () => {
    const d = collectionsAdapter.detail(collectionBrowseItem(coll({ mod_count: 1, endorsements: 0 })));
    expect(d.byline).toBe('by Kap · 1 mod');                 // singular, no endorsement clause
    expect(d.description).toBe('better world');
  });
  it('is installed (terminal, no item-level uninstall) once a member mod is tagged', () => {
    expect(collectionsAdapter.noUninstall).toBe(true);
    // No installed mods → not installed.
    expect(collectionsAdapter.installedIds({ installed_mods: [] } as any).size).toBe(0);
    // A mod tagged collection:vmu2j4 → the collection reads as installed (matches item.installId).
    const game = { installed_mods: [{ sources: { 'collection:vmu2j4': { name: 'Worldly', image: '' } } }] } as any;
    expect(collectionsAdapter.installedIds(game).has('collection:vmu2j4')).toBe(true);
  });
});

describe('collectionVenues', () => {
  it('maps a Nexus game to the collections adapter; other venues have none (yet)', () => {
    expect(collectionsAdapterFor('nexus')).toBe(collectionsAdapter);
    expect(collectionsAdapterFor('thunderstore')).toBeNull();
    expect(collectionsAdapterFor(undefined)).toBeNull();
  });
  it('venueHasCollections gates the tab on the game venue', () => {
    expect(venueHasCollections({ catalog_type: 'nexus' } as GameStatus)).toBe(true);
    expect(venueHasCollections({ catalog_type: 'workshop' } as GameStatus)).toBe(false);
  });
});
