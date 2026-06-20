import { describe, it, expect } from 'vitest';
import { nexusItem, nexusDetail } from './nexusAdapter';
import { workshopItem, workshopDetail, fmtSubs } from './workshopAdapter';
import type { ThunderstorePackage, WorkshopCatalogItem } from '../../types';

// The adapters' pure mappers normalize each venue's payload into the shared BrowseItem/BrowseDetail.
// (importing the adapters pulls in @decky, mocked in test/setup.ts.)

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
      iconUrl: 'http://icon', raw: tsPkg(),
    });
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
