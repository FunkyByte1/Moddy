import { toaster } from '@decky/api';

import { ThunderstorePackage } from '../../types';
import { getNexusCatalog, enqueueNexus } from '../../lib/api';
import { BrowseItem, BrowseDetail, PagedVenueAdapter } from './types';

// Nexus catalog items reuse the ThunderstorePackage shape (the backend emits one CatalogItem type).
export function nexusItem(p: ThunderstorePackage): BrowseItem {
  return {
    key: p.full_name,
    installId: p.full_name.toLowerCase(),
    title: p.name,
    subtitle: p.owner,
    iconUrl: p.latest.icon,
    isLibrary: !!p.is_library,
    raw: p,
  };
}

export function nexusDetail(p: ThunderstorePackage): BrowseDetail {
  const byline =
    `by ${p.owner}` +
    (p.latest.version_number ? ` · v${p.latest.version_number}` : '') +
    (p.date_updated ? ` · updated ${p.date_updated.slice(0, 10)}` : '');
  return { byline, tags: [], description: p.latest.description };
}

export const nexusAdapter: PagedVenueAdapter = {
  id: 'nexus',
  searchLabel: 'Search Nexus',
  catalogName: 'Nexus',
  sourceLabel: 'nexus',
  installModel: 'queue',
  hasFilter: true,
  emptyText: 'Catalog unavailable — set your Nexus API key in the Moddy panel and check your network.',

  async fetchPage(game, query, page, filter) {
    // Adult content and sort order are both server-side, so they're part of the query.
    const data = await getNexusCatalog(game.appid, query, page, filter?.showNsfw ?? false, filter?.sortBy || 'popularity');
    return data.map(nexusItem);
  },
  installedIds(game) {
    return new Set(game.installed_mods.map(m => m.id.toLowerCase()));
  },
  detail(item) {
    return nexusDetail(item.raw as ThunderstorePackage);
  },
  uninstallId(_game, item) {
    return item.key; // full_name
  },
  install(item, ctx) {
    // Hand to the background queue; the optimistic pending mark shows busy until the job appears.
    ctx.addPending(item.key);
    enqueueNexus(ctx.game.appid, item.key, item.title, null).catch(() => {
      ctx.removePending(item.key);
      toaster.toast({ title: 'Moddy', body: `Failed to queue ${item.title}` });
    });
  },
};
