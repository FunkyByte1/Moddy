import { InstalledMod } from './types';

/**
 * The human-facing display name for an installed mod: the catalog/meta name when we
 * have it, otherwise the on-disk filename with a trailing ".dll" stripped, otherwise
 * the mod id. Centralizes a derivation that was copy-pasted — with subtly inconsistent
 * fallbacks (`??` vs `||`, `.replace('.dll','')` vs `/\.dll$/`, with or without the id
 * fallback) — across the Installed/Profiles/Browse tabs and orphan cleanup.
 *
 * `fallbackId` is used when the mod object itself may be missing (e.g. a dependency id
 * that didn't resolve to an installed record).
 */
export function modDisplayName(
  mod: Pick<InstalledMod, 'meta' | 'filename' | 'id'> | null | undefined,
  fallbackId?: string,
): string {
  if (!mod) return fallbackId ?? '';
  return mod.meta?.name || mod.filename.replace(/\.dll$/, '') || mod.id || fallbackId || '';
}
