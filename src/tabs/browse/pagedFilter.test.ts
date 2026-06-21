import { describe, it, expect } from 'vitest';
import { pagedVisible, BrowsePagedFilter } from './pagedFilter';
import { BrowseItem } from './types';

// pagedVisible decides which loaded Nexus items show under the Browse filter: hide-libraries first,
// then install status. Pure, so it's unit-tested directly (mirrors installedMatchesFilter).

const item = (over: Partial<BrowseItem> = {}): BrowseItem => ({
  key: 'k', installId: 'k', title: 't', subtitle: 's', iconUrl: '', raw: null, ...over,
});
const filter = (over: Partial<BrowsePagedFilter> = {}): BrowsePagedFilter => ({
  installed: true, notInstalled: true, showNsfw: false, hideLibraries: true, ...over,
});

describe('pagedVisible', () => {
  it('hides library items when hideLibraries is on', () => {
    const items = [item({ installId: 'a' }), item({ installId: 'b', isLibrary: true })];
    expect(pagedVisible(items, filter(), new Set()).map(i => i.installId)).toEqual(['a']);
  });
  it('shows library items when hideLibraries is off', () => {
    const items = [item({ installId: 'a' }), item({ installId: 'b', isLibrary: true })];
    expect(pagedVisible(items, filter({ hideLibraries: false }), new Set()).map(i => i.installId)).toEqual(['a', 'b']);
  });
  it('filters by install status independently of libraries', () => {
    const items = [item({ installId: 'a' }), item({ installId: 'b' })];
    const installed = new Set(['a']);
    expect(pagedVisible(items, filter({ notInstalled: false }), installed).map(i => i.installId)).toEqual(['a']);
    expect(pagedVisible(items, filter({ installed: false }), installed).map(i => i.installId)).toEqual(['b']);
  });
});
