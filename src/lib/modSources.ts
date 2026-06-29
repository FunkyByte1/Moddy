// Provenance helpers for the Installed page's collection grouping. A mod's `sources` map is
// {sourceId -> display name}, where sourceId is "manual" or "collection:<slug>". A mod can carry
// several (installed directly AND via one or more collections) — it's still ONE mod, shown once,
// just tagged with where it came from. These are pure so they're unit-tested without the UI.

// A source value is normally {name, image} (image is the collection's tile url); a bare string
// (name only) is tolerated for forward/backward safety.
export type ModSourceValue = string | { name?: string; image?: string };
export type ModSources = Record<string, ModSourceValue>;

export interface CollectionSource {
  slug: string;
  name: string;
  image: string;
}

export interface InstalledCollection {
  slug: string;
  name: string;
  image: string;
  count: number;  // how many installed mods belong to this collection
}

const COLLECTION_PREFIX = 'collection:';

const srcName = (v: ModSourceValue): string => (typeof v === 'string' ? v : (v?.name ?? ''));
const srcImage = (v: ModSourceValue): string => (typeof v === 'string' ? '' : (v?.image ?? ''));
const byName = (a: { name: string }, b: { name: string }) =>
  a.name.localeCompare(b.name, undefined, { sensitivity: 'base' });

/** The collection memberships in a mod's sources map (drops the "manual" / "You" source). */
export function collectionSources(sources?: ModSources | null): CollectionSource[] {
  if (!sources) return [];
  return Object.entries(sources)
    .filter(([id]) => id.startsWith(COLLECTION_PREFIX))
    .map(([id, v]) => {
      const slug = id.slice(COLLECTION_PREFIX.length);
      return { slug, name: srcName(v) || slug, image: srcImage(v) };
    });
}

/** True if a mod belongs to the given collection slug. */
export function inCollection(sources: ModSources | null | undefined, slug: string): boolean {
  return !!sources && (COLLECTION_PREFIX + slug) in sources;
}

/** Short tag for a mod row: the collection name (with "+N" if it's in several), or null when the
 *  mod is only a direct install — those need no tag ("yours" is the implicit default). */
export function sourceTagLabel(sources?: ModSources | null): string | null {
  const cols = collectionSources(sources);
  if (cols.length === 0) return null;
  const first = [...cols].sort(byName)[0];
  return cols.length === 1 ? first.name : `${first.name} +${cols.length - 1}`;
}

/** The primary collection to badge a mod row with — its tile image + name, plus how many OTHER
 *  collections also include the mod ("+N"). Null when the mod came from no collection. */
export function primaryCollection(sources?: ModSources | null): { name: string; image: string; extra: number } | null {
  const cols = collectionSources(sources);
  if (cols.length === 0) return null;
  const first = [...cols].sort(byName)[0];
  return { name: first.name, image: first.image, extra: cols.length - 1 };
}

/** The distinct collections present across a set of installed mods, with how many mods each brought
 *  in, sorted by name — drives the Installed page's Collections section. `mods` is anything carrying
 *  a `sources` map (InstalledMod / ModEntry). */
export function installedCollections(mods: { sources?: ModSources | null }[]): InstalledCollection[] {
  const bySlug = new Map<string, InstalledCollection>();
  for (const m of mods) {
    for (const c of collectionSources(m.sources)) {
      const existing = bySlug.get(c.slug);
      if (existing) { existing.count++; if (!existing.image && c.image) existing.image = c.image; }
      else bySlug.set(c.slug, { slug: c.slug, name: c.name, image: c.image, count: 1 });
    }
  }
  return [...bySlug.values()].sort(byName);
}
