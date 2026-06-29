import { describe, it, expect } from 'vitest';
import {
  collectionSources, inCollection, sourceTagLabel, primaryCollection, installedCollections,
} from './modSources';

// modSources turns a mod's flat {sourceId -> name} provenance map into the Installed page's
// grouping: per-row tags, membership tests, and the distinct-collections list. A mod can be in
// several collections (and/or installed manually) — it's still one mod, tagged with all of them.

describe('collectionSources', () => {
  it('returns only collection memberships with name+image, dropping manual', () => {
    expect(collectionSources({
      manual: { name: 'You', image: '' },
      'collection:abc': { name: 'Worldly', image: 'u.png' },
    })).toEqual([{ slug: 'abc', name: 'Worldly', image: 'u.png' }]);
  });
  it('tolerates a bare-string value (name only, no image)', () => {
    expect(collectionSources({ 'collection:abc': 'Worldly' }))
      .toEqual([{ slug: 'abc', name: 'Worldly', image: '' }]);
  });
  it('falls back to the slug when a name is missing', () => {
    expect(collectionSources({ 'collection:abc': { name: '', image: '' } }))
      .toEqual([{ slug: 'abc', name: 'abc', image: '' }]);
  });
  it('is empty for no sources / manual-only', () => {
    expect(collectionSources(null)).toEqual([]);
    expect(collectionSources({ manual: { name: 'You' } })).toEqual([]);
  });
});

describe('inCollection', () => {
  it('matches by slug', () => {
    expect(inCollection({ 'collection:abc': { name: 'Worldly' } }, 'abc')).toBe(true);
    expect(inCollection({ 'collection:abc': { name: 'Worldly' } }, 'xyz')).toBe(false);
    expect(inCollection(null, 'abc')).toBe(false);
  });
});

describe('sourceTagLabel', () => {
  it('is null for a manual-only / untracked mod (no tag needed)', () => {
    expect(sourceTagLabel(null)).toBeNull();
    expect(sourceTagLabel({ manual: { name: 'You' } })).toBeNull();
  });
  it('shows the collection name for a single membership', () => {
    expect(sourceTagLabel({ 'collection:abc': { name: 'Worldly' } })).toBe('Worldly');
  });
  it('shows name +N for multiple memberships, name-sorted', () => {
    expect(sourceTagLabel({
      'collection:a': { name: 'Renn’s' }, 'collection:b': { name: 'Aloy' }, manual: { name: 'You' },
    })).toBe('Aloy +1');
  });
});

describe('primaryCollection', () => {
  it('is null for a manual-only / untracked mod', () => {
    expect(primaryCollection(null)).toBeNull();
    expect(primaryCollection({ manual: { name: 'You' } })).toBeNull();
  });
  it('returns the first collection (name-sorted) with image + extra count', () => {
    expect(primaryCollection({ 'collection:abc': { name: 'Worldly', image: 'w.png' } }))
      .toEqual({ name: 'Worldly', image: 'w.png', extra: 0 });
    expect(primaryCollection({
      'collection:a': { name: 'Zebra', image: 'z.png' },
      'collection:b': { name: 'Apple', image: 'a.png' },
      manual: { name: 'You' },
    })).toEqual({ name: 'Apple', image: 'a.png', extra: 1 });
  });
});

describe('installedCollections', () => {
  it('counts mods per collection, keeps an image, and sorts by name', () => {
    const mods = [
      { sources: { 'collection:z': { name: 'Zebra', image: 'z.png' }, manual: { name: 'You' } } },
      { sources: { 'collection:a': { name: 'Apple', image: '' } } },
      { sources: { 'collection:a': { name: 'Apple', image: 'a.png' }, 'collection:z': { name: 'Zebra', image: 'z.png' } } },
      { sources: { manual: { name: 'You' } } },  // direct-only — contributes to no collection
      { sources: null },                          // legacy/untracked
    ];
    expect(installedCollections(mods)).toEqual([
      { slug: 'a', name: 'Apple', image: 'a.png', count: 2 },  // image filled in from the 2nd mod
      { slug: 'z', name: 'Zebra', image: 'z.png', count: 2 },
    ]);
  });
  it('is empty when nothing came from a collection', () => {
    expect(installedCollections([{ sources: { manual: { name: 'You' } } }, { sources: null }])).toEqual([]);
  });
});
