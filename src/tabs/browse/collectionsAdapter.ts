import { toaster } from '@decky/api';

import { CollectionItem } from '../../types';
import { getCollectionsCatalog, enqueueCollection } from '../../lib/api';
import { installedCollections } from '../../lib/modSources';
import { BrowseItem, BrowseDetail, PagedVenueAdapter } from './types';
import CollectionBrowseDetail from './CollectionBrowseDetail';

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
  // A collection is installed as a whole set; it's managed/removed from the Installed tab, not
  // item-by-item here — so an already-installed collection shows a disabled "Installed", not "Uninstall".
  noUninstall: true,
  emptyText: 'No collections found — set your Nexus API key in the Moddy panel and check your network.',
  installNotice: 'Installs every required mod in this collection (with the curator’s installer choices). This can take a while; watch the download queue.',

  async fetchPage(game, query, page) {
    const data = await getCollectionsCatalog(game.appid, query, page);
    return data.map(collectionBrowseItem);
  },
  // A collection counts as installed once any of its mods are present (tagged collection:<slug> on
  // their records) — so the button flips to "Installed" after the queue job finishes. installId is
  // `collection:<slug>`, matching the item key.
  installedIds(game) {
    return new Set(installedCollections(game.installed_mods).map(c => `collection:${c.slug}`));
  },
  detail(item): BrowseDetail {
    const c = item.raw as CollectionItem;
    const byline = `by ${c.author} · ${c.mod_count} mod${c.mod_count === 1 ? '' : 's'}`
      + (c.endorsements ? ` · ${c.endorsements} endorsement${c.endorsements === 1 ? '' : 's'}` : '');
    return { byline, tags: [], description: c.summary };
  },
  // Under the description, list the collection's mods (lazily fetched).
  DetailExtra: CollectionBrowseDetail,
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

// Thunderstore modpacks reuse the exact same browse/install/uninstall machinery as Nexus collections
// — the backend RPCs (catalog/detail/enqueue) route by the game's venue, and a modpack arrives in the
// same CollectionItem shape (slug = the modpack's full_name). Only the display strings differ, to use
// Thunderstore's own terminology ("Modpacks", "likes"). Everything else is inherited.
export const modpacksAdapter: PagedVenueAdapter = {
  ...collectionsAdapter,
  id: 'modpacks',
  sourceLabel: 'thunderstore',
  searchLabel: 'Search modpacks',
  catalogName: 'Modpacks',
  emptyText: 'No modpacks found — check your network and try again.',
  installNotice: 'Installs every mod in this modpack (its full set of dependencies). This can take a while; watch the download queue.',
  detail(item): BrowseDetail {
    const c = item.raw as CollectionItem;
    const byline = `by ${c.author} · ${c.mod_count} mod${c.mod_count === 1 ? '' : 's'}`
      + (c.endorsements ? ` · ${c.endorsements} like${c.endorsements === 1 ? '' : 's'}` : '');
    return { byline, tags: [], description: c.summary };
  },
};
