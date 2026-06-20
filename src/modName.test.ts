import { describe, it, expect } from 'vitest';
import { modDisplayName } from './modName';

// Zero-runtime-dependency canary: modName.ts's only import is a type (erased by esbuild), so this
// proves the Vitest + TS toolchain works without touching the Decky mocks.
describe('modDisplayName', () => {
  it('prefers the meta name', () => {
    expect(modDisplayName({ meta: { name: 'Cool Mod' }, filename: 'cool.dll', id: 'Owner-Cool' }))
      .toBe('Cool Mod');
  });

  it('falls back to the filename with a trailing .dll stripped', () => {
    expect(modDisplayName({ meta: null, filename: 'CoolMod.dll', id: 'Owner-Cool' })).toBe('CoolMod');
  });

  it('keeps a filename that has no .dll suffix', () => {
    expect(modDisplayName({ meta: null, filename: 'nexus-12345', id: 'nexus.x.1' })).toBe('nexus-12345');
  });

  it('treats an empty meta name as absent and falls through', () => {
    expect(modDisplayName({ meta: { name: '' }, filename: 'Bar.dll', id: 'Owner-Bar' })).toBe('Bar');
  });

  it('falls back to the id when meta name and filename are both empty', () => {
    expect(modDisplayName({ meta: { name: '' }, filename: '', id: 'Owner-Bar' })).toBe('Owner-Bar');
  });

  it('uses the mod id before the fallbackId when the mod is present', () => {
    expect(modDisplayName({ meta: null, filename: '', id: 'real-id' }, 'fallback')).toBe('real-id');
  });

  it('returns the fallbackId when the mod is missing', () => {
    expect(modDisplayName(null, 'fallback')).toBe('fallback');
    expect(modDisplayName(undefined, 'fallback')).toBe('fallback');
  });

  it('returns an empty string for a missing mod with no fallbackId', () => {
    expect(modDisplayName(null)).toBe('');
    expect(modDisplayName(undefined)).toBe('');
  });
});
