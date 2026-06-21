import { GameStatus } from '../../types';

// Normalized list item every paged venue (Nexus, Workshop) produces from its own payload, so the
// shared BrowseTab renders/installs/uninstalls uniformly. `raw` keeps the venue payload for the
// adapter's own handlers.
export interface BrowseItem {
  key: string;        // React key + page-dedup + selection identity (full_name | workshop fileId)
  installId: string;  // value checked against installedIds() to decide "installed"
  title: string;
  subtitle: string;   // "owner" | "1.2k subscribers"
  iconUrl: string;
  raw: unknown;       // ThunderstorePackage (Nexus) | WorkshopCatalogItem (Workshop)
}

// Detail-panel content beyond title/icon.
export interface BrowseDetail {
  byline: string;     // line under the title ("by owner · v1.2 · updated …" / "1.2k subscribers · …")
  tags: string[];     // Workshop tags; [] otherwise
  description: string; // already cleaned (Workshop strips BBCode)
}

// Tools the adapter's install() uses to drive busy state + refresh.
export interface InstallContext {
  game: GameStatus;
  onRefresh: () => Promise<void>;
  setInstalling: (id: string | null) => void;
  addPending: (ref: string) => void;
  removePending: (ref: string) => void;
}

// Per-venue adapter for the shared paged BrowseTab. Captures only what differs between Nexus and
// Workshop; the component owns the shared list/detail/focus/search scaffolding.
export interface PagedVenueAdapter {
  id: 'nexus' | 'workshop';
  searchLabel: string;                 // "Search Nexus"
  sourceLabel: 'nexus' | 'workshop';   // <CatalogSourceLabel source=...>
  installModel: 'queue' | 'inline';    // queue → optimistic pending + queue footer; inline → local busy
  hasFilter: boolean;                  // Nexus: filter button + client installed-status filter
  emptyText: string;                   // "Catalog unavailable — …" when the first page is empty (no search)
  installNotice?: string;              // Workshop: shown under the Install button (only when not installed)
                                       // so the user knows the action subscribes them via their Steam account

  // `sort` is the venue's own sort key (Nexus); Workshop ignores it.
  fetchPage(game: GameStatus, query: string, page: number, nsfw: boolean, sort: string): Promise<BrowseItem[]>;
  installedIds(game: GameStatus): Set<string>;
  detail(item: BrowseItem): BrowseDetail;
  uninstallId(game: GameStatus, item: BrowseItem): string; // recorded id used for uninstall + dependents
  install(item: BrowseItem, ctx: InstallContext): void;
}
