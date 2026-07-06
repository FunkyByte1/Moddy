import { showModal } from '@decky/ui';
import { toaster } from '@decky/api';

import {
  GameStatus, ThunderstorePackage,
} from '../../types';
import {
  getThunderstoreCatalog, getBmiCatalog, getBrowseDenylist,
  enqueueThunderstore, enqueueBmi, getUnresolvedDependencies,
} from '../../lib/api';
import DependencyChecklistModal from '../../components/modals/DependencyChecklistModal';
import { transitiveCatalogDeps } from '../../lib/browseDeps';
import { stripVersion } from '../../lib/modGraph';
import { BrowsePagedFilter } from './pagedFilter';
import { BrowseItem, BrowseDetail, InstallContext, PagedVenueAdapter } from './types';

// Thunderstore + BMI browse a whole cached catalog and client-page it through the shared
// BrowsePagedTab (so the list is never virtualized — only the loaded slices are rendered). Both
// venues share this factory; they differ only in catalog source, enqueue call, and whether they
// resolve dependencies (Thunderstore does; BMI items declare none).

const PAGE = 25;

// ── pure helpers (exported for unit tests) ─────────────────────────────────

const libCategorySet = (game: GameStatus): Set<string> =>
  new Set((game.library_categories ?? []).map(c => c.toLowerCase()));

const isLibraryPkg = (p: ThunderstorePackage, libSet: Set<string>): boolean =>
  p.categories.some(c => libSet.has(c.toLowerCase()));

// Thunderstore's curated-pack category. Modpacks have their own Collections tab (and are often
// dual-tagged 'Mods'+'Modpacks'), so they're kept out of the mods Browse list entirely — mirrors
// the backend's is_modpack (thunderstore_modpacks.py).
const MODPACK_CATEGORY = 'modpacks';
const isModpackPkg = (p: ThunderstorePackage): boolean =>
  p.categories.some(c => c.toLowerCase() === MODPACK_CATEGORY);

export function catalogItem(p: ThunderstorePackage, libSet: Set<string>): BrowseItem {
  return {
    key: p.full_name,
    installId: p.full_name.toLowerCase(),
    title: p.name,
    subtitle: p.owner,
    iconUrl: p.latest.icon,
    isLibrary: isLibraryPkg(p, libSet),
    raw: p,
  };
}

export function catalogDetail(p: ThunderstorePackage): BrowseDetail {
  const byline =
    `by ${p.owner} · v${p.latest.version_number}` +
    (p.rating_score > 0
      ? ` · ${p.rating_score} likes`
      : p.date_updated ? ` · updated ${p.date_updated.slice(0, 10)}` : '');
  // The categories double as the detail "tags" row; deprecated surfaces the ⚠ line in BrowsePagedTab.
  return { byline, tags: p.categories, description: p.latest.description, deprecated: p.is_deprecated };
}

// Denylist + deprecated/nsfw/category/search/sort, mirroring BrowseTab.filtered. install-status and
// hide-libraries are intentionally NOT applied here — the component's pagedVisible applies those two
// (instant, no refetch), exactly as it does for Nexus.
export function filterCatalog(
  catalog: ThunderstorePackage[],
  denylist: Set<string>,
  query: string,
  filter?: BrowsePagedFilter,
): ThunderstorePackage[] {
  const showDeprecated = filter?.showDeprecated ?? false;
  const showNsfw = filter?.showNsfw ?? false;
  const cats = filter?.categories;
  let list = catalog.filter(p => {
    if (denylist.has(p.full_name.toLowerCase())) return false;
    if (isModpackPkg(p)) return false;  // curated packs live in the Collections tab, not the mods list
    if (p.is_deprecated && !showDeprecated) return false;
    if (p.has_nsfw_content && !showNsfw) return false;
    if (cats && cats.length > 0 && !p.categories.some(c => cats.includes(c))) return false;
    return true;
  });
  const q = query.toLowerCase().trim();
  if (q) {
    list = list.filter(p =>
      p.full_name.toLowerCase().includes(q) || p.latest.description.toLowerCase().includes(q));
  }
  const sorted = [...list];
  switch (filter?.sortBy) {
    case 'name': sorted.sort((a, b) => a.name.localeCompare(b.name)); break;
    // ISO date strings sort lexically, newest first.
    case 'updated': sorted.sort((a, b) => (b.date_updated ?? '').localeCompare(a.date_updated ?? '')); break;
    case 'rating':
    default: sorted.sort((a, b) => b.rating_score - a.rating_score); break;
  }
  return sorted;
}

// Non-library categories present in the (non-denylisted) catalog, sorted — surfaced to the filter modal.
export function catalogCategories(
  catalog: ThunderstorePackage[],
  denylist: Set<string>,
  libSet: Set<string>,
): string[] {
  const set = new Set<string>();
  for (const p of catalog) {
    if (denylist.has(p.full_name.toLowerCase())) continue;
    if (isModpackPkg(p)) continue;  // modpacks aren't in the mods list, so don't offer 'Modpacks' as a filter
    for (const c of p.categories) if (!libSet.has(c.toLowerCase())) set.add(c);
  }
  return [...set].sort();
}

// ── adapter factory ────────────────────────────────────────────────────────

type EnqueueFn = (appid: number, fullName: string, name: string, withDeps: boolean, allowMissing: boolean) => Promise<number>;

interface CatalogVenue {
  id: 'thunderstore' | 'bmi';
  catalogName: string;
  sourceLabel: 'thunderstore' | 'bmi';
  emptyText: string;
  hasDeps: boolean;                                    // Thunderstore resolves deps; BMI items have none
  fetchCatalog: (appid: number) => Promise<ThunderstorePackage[]>;
  enqueue: EnqueueFn;
}

interface CatalogEntry { catalog: ThunderstorePackage[]; denylist: Set<string>; refreshKey: number; }

function makeCatalogAdapter(venue: CatalogVenue): PagedVenueAdapter {
  // Full catalog + denylist cached per game; re-fetched only when refreshKey changes (the
  // Options-menu "Refresh Catalog" bumps it). The denylist is global but cached alongside per appid.
  const cache = new Map<number, CatalogEntry>();

  const ensure = async (appid: number, refreshKey?: number): Promise<CatalogEntry> => {
    const key = refreshKey ?? 0;
    const hit = cache.get(appid);
    if (hit && hit.refreshKey === key) return hit;
    const [catalog, deny] = await Promise.all([venue.fetchCatalog(appid), getBrowseDenylist()]);
    const entry: CatalogEntry = { catalog, denylist: new Set(deny.map(d => d.toLowerCase())), refreshKey: key };
    cache.set(appid, entry);
    return entry;
  };

  // Installs go to the background download queue; the optimistic pending mark hands off to the job.
  const runInstall = (ctx: InstallContext, p: ThunderstorePackage, withDeps: boolean, allowMissing: boolean) => {
    ctx.addPending(p.full_name);
    venue.enqueue(ctx.game.appid, p.full_name, p.name, withDeps, allowMissing).catch(() => {
      ctx.removePending(p.full_name);
      toaster.toast({ title: 'Moddy', body: `Failed to queue ${p.name}` });
    });
  };

  // The mod's resolvable, not-installed, not-already-in-flight dependencies (Thunderstore only). The
  // in-flight set (active queue jobs + just-clicked refs, walked transitively) is dropped so we never
  // re-offer a dep an earlier install already covers.
  const depEntries = (p: ThunderstorePackage, entry: CatalogEntry, ctx: InstallContext) => {
    const installed = new Set(ctx.game.installed_mods.map(m => m.id.toLowerCase()));
    const inFlight = new Set<string>([...ctx.queuedRefs, ...[...ctx.pending].map(s => s.toLowerCase())]);
    const pendingDepIds = transitiveCatalogDeps(entry.catalog, inFlight);
    return p.latest.dependencies
      .map(d => ({ id: stripVersion(d), version: d.split('-').slice(-1)[0] }))
      .filter(e => e.id && !entry.denylist.has(e.id.toLowerCase())
        && !installed.has(e.id.toLowerCase()) && !pendingDepIds.has(e.id.toLowerCase()))
      .map(e => ({
        id: e.id,
        version: e.version,
        name: entry.catalog.find(c => c.full_name.toLowerCase() === e.id.toLowerCase())?.name ?? e.id,
      }));
  };

  // "Install with options…": install the mod alone, then enqueue only the deps the user kept.
  const installSelective = (ctx: InstallContext, p: ThunderstorePackage, selectedIds: string[]) => {
    runInstall(ctx, p, false, true);
    const entry = cache.get(ctx.game.appid);
    for (const depId of selectedIds) {
      const depPkg = entry?.catalog.find(c => c.full_name.toLowerCase() === depId.toLowerCase());
      ctx.addPending(depId);
      enqueueThunderstore(ctx.game.appid, depId, depPkg?.name ?? depId, null, true, true).catch(() => {
        ctx.removePending(depId);
        toaster.toast({ title: 'Moddy', body: `Failed to queue ${depPkg?.name ?? depId}` });
      });
    }
  };

  const adapter: PagedVenueAdapter = {
    id: venue.id,
    searchLabel: `Search ${venue.catalogName}`,
    catalogName: venue.catalogName,
    sourceLabel: venue.sourceLabel,
    installModel: 'queue',
    hasFilter: true,
    emptyText: venue.emptyText,

    async fetchPage(game, query, page, filter, refreshKey) {
      const entry = await ensure(game.appid, refreshKey);
      const libSet = libCategorySet(game);
      const list = filterCatalog(entry.catalog, entry.denylist, query, filter);
      return list.slice((page - 1) * PAGE, page * PAGE).map(p => catalogItem(p, libSet));
    },
    fetchKey(filter) {
      // Inputs filterCatalog reads (NOT hide-libraries / install-status — those are pagedVisible's,
      // applied instantly). Any change here resets to page 1 and re-slices the cached catalog.
      return `${filter?.showNsfw ?? false}|${filter?.showDeprecated ?? false}|${filter?.sortBy ?? ''}|${(filter?.categories ?? []).join(',')}`;
    },
    categories(game) {
      const entry = cache.get(game.appid);
      return entry ? catalogCategories(entry.catalog, entry.denylist, libCategorySet(game)) : [];
    },
    installedIds(game) {
      return new Set(game.installed_mods.map(m => m.id.toLowerCase()));
    },
    detail(item) {
      return catalogDetail(item.raw as ThunderstorePackage);
    },
    uninstallId(_game, item) {
      return item.key; // full_name
    },
    install(item, ctx) {
      const p = item.raw as ThunderstorePackage;
      if (!venue.hasDeps) { runInstall(ctx, p, true, false); return; }
      // Plain install pulls all deps; if some declared deps aren't in the catalog, install anyway and
      // warn rather than block (matching BrowseTab). Per-dep control lives behind "Install with options…".
      void (async () => {
        const unresolved = await getUnresolvedDependencies(ctx.game.appid, p.full_name).catch(() => [] as string[]);
        if (unresolved.length > 0) {
          toaster.toast({
            title: 'Moddy',
            body: `Installing ${p.name} — ${unresolved.length} ${unresolved.length === 1 ? "dependency isn't" : "dependencies aren't"} available and won't be installed`,
          });
          runInstall(ctx, p, true, true);
        } else {
          runInstall(ctx, p, true, false);
        }
      })();
    },
  };

  if (venue.hasDeps) {
    adapter.secondaryActions = (item, installed, ctx) => {
      if (installed) return [];
      const p = item.raw as ThunderstorePackage;
      const entry = cache.get(ctx.game.appid);
      if (!entry) return [];
      const deps = depEntries(p, entry, ctx);
      if (deps.length === 0) return [];
      return [{
        label: 'Install with options…',
        run: () => showModal(
          <DependencyChecklistModal
            modName={p.name}
            dependencies={deps}
            onInstall={(selected, close) => { close(); installSelective(ctx, p, selected); }}
          />,
        ),
      }];
    };
    // Thunderstore records deps as version-suffixed full_names, so dependents must version-strip to
    // match this mod's id — the generic includes(uid) the component falls back to would miss them.
    adapter.dependents = (game, item) => {
      const fn = item.key.toLowerCase();
      return game.installed_mods.filter(m =>
        (m.meta?.dependencies ?? []).some(d => stripVersion(d).toLowerCase() === fn));
    };
  }

  return adapter;
}

export const thunderstoreAdapter = makeCatalogAdapter({
  id: 'thunderstore',
  catalogName: 'Thunderstore',
  sourceLabel: 'thunderstore',
  emptyText: 'Catalog unavailable — check your network and try again.',
  hasDeps: true,
  fetchCatalog: getThunderstoreCatalog,
  enqueue: (appid, fn, name, withDeps, allowMissing) =>
    enqueueThunderstore(appid, fn, name, null, withDeps, allowMissing),
});

export const bmiAdapter = makeCatalogAdapter({
  id: 'bmi',
  catalogName: 'BMI',
  sourceLabel: 'bmi',
  emptyText: 'Catalog unavailable — check your network and try again.',
  hasDeps: false,
  fetchCatalog: getBmiCatalog,
  enqueue: (appid, fn, name) => enqueueBmi(appid, fn, name, null),
});
