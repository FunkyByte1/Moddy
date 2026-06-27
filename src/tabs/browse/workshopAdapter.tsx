import { showModal } from '@decky/ui';
import { toaster } from '@decky/api';

import {
  GameStatus, WorkshopCatalogItem,
} from '../../types';
import {
  getWorkshopCatalog, getWorkshopRequiredItems, installWorkshopTree, workshopModId, fileIdForMod,
} from '../../lib/api';
import DependencyInstallModal from '../../components/modals/DependencyInstallModal';
import { BrowseItem, BrowseDetail, PagedVenueAdapter } from './types';

export const fmtSubs = (n: number): string =>
  n >= 1000 ? `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}k` : `${n}`;
const stripBBCode = (s: string): string => s.replace(/\[\/?[^\]]+\]/g, '').trim();

export function workshopItem(it: WorkshopCatalogItem): BrowseItem {
  return {
    key: it.id,
    installId: it.id,
    title: it.name,
    subtitle: `${fmtSubs(it.subscriptions)} subscribers`,
    iconUrl: it.preview_url,
    raw: it,
  };
}

export function workshopDetail(it: WorkshopCatalogItem): BrowseDetail {
  const byline =
    `${fmtSubs(it.subscriptions)} subscribers` +
    (it.time_updated ? ` · updated ${new Date(it.time_updated * 1000).toISOString().slice(0, 10)}` : '');
  return { byline, tags: it.tags, description: stripBBCode(it.description) };
}

const workshopInstalledIds = (game: GameStatus): Set<string> =>
  new Set(game.installed_mods.map(m => fileIdForMod(game.appid, m.id)).filter(Boolean) as string[]);

export const workshopAdapter: PagedVenueAdapter = {
  id: 'workshop',
  searchLabel: 'Search Workshop',
  catalogName: 'Workshop',
  sourceLabel: 'workshop',
  installModel: 'inline',
  hasFilter: false,
  emptyText: 'Catalog unavailable — check network.',
  installNotice:
    'Installing subscribes you to this item (and any required items) through your Steam account. ' +
    'They appear in your Steam Workshop subscriptions; uninstalling unsubscribes them.',

  async fetchPage(game, query, page) {
    // Sorted by most-subscribed for now (a press-Y sort selector could re-add the option).
    const data = await getWorkshopCatalog(game.appid, query, 'subscribed', page);
    return data.map(workshopItem);
  },
  installedIds: workshopInstalledIds,
  detail(item) {
    return workshopDetail(item.raw as WorkshopCatalogItem);
  },
  uninstallId(game, item) {
    return workshopModId(game.appid, item.key);
  },
  install(item, ctx) {
    // Inline install (SteamClient subscribe), not the queue. Steam doesn't cascade an item's required
    // items, so surface the not-yet-installed ones as a confirmation gate first, then installWorkshopTree.
    const it = item.raw as WorkshopCatalogItem;
    const installed = workshopInstalledIds(ctx.game);
    const runInstall = async (withDeps: boolean) => {
      ctx.setInstalling(item.key);
      try {
        await installWorkshopTree(
          ctx.game.appid, it.id,
          { name: it.name, thumbnail: it.preview_url, description: it.description },
          new Set(), withDeps,
        );
        toaster.toast({ title: 'Moddy', body: `Installing ${it.name}…` });
        await ctx.onRefresh();
      } finally { ctx.setInstalling(null); }
    };
    void (async () => {
      ctx.setInstalling(item.key);
      let required: WorkshopCatalogItem[] = [];
      try { required = await getWorkshopRequiredItems(ctx.game.appid, it.id); } catch { /* install without the prompt */ }
      ctx.setInstalling(null);
      const missing = required.filter(r => !installed.has(r.id));
      if (missing.length > 0) {
        showModal(
          <DependencyInstallModal
            modName={it.name}
            dependencyNames={missing.map(r => r.name)}
            onInstall={close => { close(); runInstall(true); }}
            onSkip={close => { close(); runInstall(false); }}
          />,
        );
        return;
      }
      runInstall(true);
    })();
  },
};
