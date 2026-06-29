import { toaster } from '@decky/api';

import { CollectionItem } from '../../types';
import { getCollectionsCatalog, enqueueCollection } from '../../lib/api';
import { BrowseItem, BrowseDetail, PagedVenueAdapter } from './types';

// Browse-and-install Nexus collections. Reuses the shared paged Browse tab: list collections for the
// game (server-paginated), and installing one enqueues its WHOLE required mod set (pinned files +
// replayed FOMOD choices) as a single background job — so unlike the mod venues, an item isn't
// "installed/uninstalled" individually. The job's queue ref is `collection:<slug>`, which the item
// key mirrors so the optimistic busy mark hands off to the real queue job.
export function collectionBrowseItem(c: CollectionItem): BrowseItem {
  return {
    key: `collection:${c.slug}`,
    installId: `collection:${c.slug}`,
    title: c.name,
    subtitle: `by ${c.author} · ${c.mod_count} mod${c.mod_count === 1 ? '' : 's'}`,
    iconUrl: c.tile_image,
    isLibrary: false,
    raw: c,
  };
}

export const collectionsAdapter: PagedVenueAdapter = {
  id: 'collections',
  searchLabel: 'Search collections',
  catalogName: 'Collections',
  sourceLabel: 'nexus',
  installModel: 'queue',
  hasFilter: false,
  emptyText: 'No collections found — set your Nexus API key in the Moddy panel and check your network.',
  installNotice: 'Installs every required mod in this collection (with the curator’s installer choices). This can take a while; watch the download queue.',

  async fetchPage(game, query, page) {
    const data = await getCollectionsCatalog(game.appid, query, page);
    return data.map(collectionBrowseItem);
  },
  // Collections aren't tracked as installed — the install action always installs the whole set.
  installedIds() {
    return new Set<string>();
  },
  detail(item): BrowseDetail {
    const c = item.raw as CollectionItem;
    const byline = `by ${c.author} · ${c.mod_count} mod${c.mod_count === 1 ? '' : 's'}`
      + (c.endorsements ? ` · ${c.endorsements} endorsement${c.endorsements === 1 ? '' : 's'}` : '');
    return { byline, tags: [], description: c.summary };
  },
  uninstallId(_game, item) {
    return item.key;
  },
  install(item, ctx) {
    const c = item.raw as CollectionItem;
    ctx.addPending(item.key);
    enqueueCollection(ctx.game.appid, c.slug)
      .then(jobId => {
        if (jobId < 0) {
          ctx.removePending(item.key);
          toaster.toast({ title: 'Moddy', body: `Couldn’t queue collection ${c.name}` });
        }
      })
      .catch(() => {
        ctx.removePending(item.key);
        toaster.toast({ title: 'Moddy', body: `Failed to queue ${c.name}` });
      });
  },
};
