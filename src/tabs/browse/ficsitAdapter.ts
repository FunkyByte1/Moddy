import { toaster } from '@decky/api';

import { ThunderstorePackage, getFicsitCatalog, enqueueFicsit } from '../../types';
import { BrowseItem, BrowseDetail, PagedVenueAdapter } from './types';

// ficsit.app (Satisfactory) catalog items reuse the shared ThunderstorePackage shape (the backend
// emits one CatalogItem type for every venue), so the rendering matches Nexus exactly.
export function ficsitItem(p: ThunderstorePackage): BrowseItem {
  return {
    key: p.full_name,                    // "ficsit.<mod_reference>"
    installId: p.full_name.toLowerCase(),
    title: p.name,
    subtitle: p.owner,
    iconUrl: p.latest.icon,
    isLibrary: !!p.is_library,
    raw: p,
  };
}

export function ficsitDetail(p: ThunderstorePackage): BrowseDetail {
  const byline =
    `by ${p.owner}` +
    (p.latest.version_number ? ` · v${p.latest.version_number}` : '') +
    (p.date_updated ? ` · updated ${p.date_updated.slice(0, 10)}` : '');
  return { byline, tags: [], description: p.latest.description };
}

export const ficsitAdapter: PagedVenueAdapter = {
  id: 'ficsit',
  searchLabel: 'Search ficsit.app',
  catalogName: 'ficsit.app',
  sourceLabel: 'ficsit',
  installModel: 'queue',
  // Server-paged by the chosen sort (default popularity) + search; the filter modal also offers
  // install-status filtering over the loaded pages (client-side via pagedVisible). No NSFW/library
  // controls — ficsit has neither (the shared modal hides those sections for ficsit).
  hasFilter: true,
  emptyText: 'Catalog unavailable — check your network and try again.',

  async fetchPage(game, query, page, filter) {
    // Sort is server-side, so it's part of the query (toggling it re-fetches).
    const data = await getFicsitCatalog(game.appid, query, page, filter?.sortBy || 'popularity');
    return data.map(ficsitItem);
  },
  installedIds(game) {
    return new Set(game.installed_mods.map(m => m.id.toLowerCase()));
  },
  detail(item) {
    return ficsitDetail(item.raw as ThunderstorePackage);
  },
  uninstallId(_game, item) {
    return item.key; // full_name ("ficsit.<mod_reference>")
  },
  install(item, ctx) {
    // Hand to the background queue; the optimistic pending mark shows busy until the job appears.
    ctx.addPending(item.key);
    enqueueFicsit(ctx.game.appid, item.key, item.title, null).catch(() => {
      ctx.removePending(item.key);
      toaster.toast({ title: 'Moddy', body: `Failed to queue ${item.title}` });
    });
  },
};
