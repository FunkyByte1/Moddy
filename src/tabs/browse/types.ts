import { GameStatus, InstalledMod } from '../../types';
import type { BrowsePagedFilter } from './pagedFilter';

// Normalized list item every paged venue (Nexus, Workshop — and, after Phase 2, Thunderstore/BMI)
// produces from its own payload, so the shared BrowsePagedTab renders/installs/uninstalls uniformly.
// `raw` keeps the venue payload for the adapter's own handlers.
export interface BrowseItem {
  key: string;        // React key + page-dedup + selection identity (full_name | workshop fileId)
  installId: string;  // value checked against installedIds() to decide "installed"
  title: string;
  subtitle: string;   // "owner" | "1.2k subscribers"
  iconUrl: string;
  isLibrary?: boolean; // framework/library mod, hidden by default. Workshop leaves it unset.
  raw: unknown;       // ThunderstorePackage (Nexus/Thunderstore) | WorkshopCatalogItem (Workshop) | BMI item
}

// Detail-panel content beyond title/icon.
export interface BrowseDetail {
  byline: string;      // line under the title ("by owner · v1.2 · updated …" / "1.2k subscribers · …")
  tags: string[];      // Workshop tags; [] otherwise
  description: string; // already cleaned (Workshop strips BBCode)
  deprecated?: boolean; // Thunderstore renders a "⚠ Deprecated" line; other venues omit it.
}

// Tools the adapter's install() / secondary actions use to drive busy state + refresh. `pending` and
// `queuedRefs` are the read side of the install hook, exposed so a dependency-cascade action
// (Thunderstore's "Install with options…") can dedup deps already installing without re-deriving the
// queue state. Nexus/Workshop install() ignore them.
export interface InstallContext {
  game: GameStatus;
  onRefresh: () => Promise<void>;
  setInstalling: (id: string | null) => void;
  addPending: (ref: string) => void;
  removePending: (ref: string) => void;
  pending: Set<string>;       // optimistic just-clicked refs (lowercased compare by the adapter)
  queuedRefs: Set<string>;    // active download-queue refs (already lowercased)
}

// A secondary action shown under the primary Install button for the selected item — e.g.
// Thunderstore's "Install with options…" dependency checklist. The adapter returns the actions
// applicable to the item in its current install state ([] = none); the component renders one button
// each. `run` is bound by the adapter when it builds the action (closing over the item + ctx).
export interface BrowseSecondaryAction {
  label: string;
  run: () => void;
}

// Per-venue adapter for the shared paged BrowsePagedTab. Captures only what differs between venues;
// the component owns the shared list/detail/focus/search scaffolding. The members below the core four
// are OPTIONAL — Nexus/Workshop omit them and keep their exact behavior; Thunderstore/BMI (Phase 2)
// implement the filtering / category / dependency-cascade hooks.
export interface PagedVenueAdapter {
  id: 'nexus' | 'workshop' | 'thunderstore' | 'bmi' | 'ficsit' | 'collections';
  searchLabel: string;                 // "Search Nexus"
  catalogName: string;                 // human label for messages, e.g. "Nexus" / "Workshop"
  sourceLabel: 'nexus' | 'workshop' | 'thunderstore' | 'bmi' | 'ficsit';  // <CatalogSourceLabel source=...>
  installModel: 'queue' | 'inline';    // queue → optimistic pending + queue footer; inline → local busy
  hasFilter: boolean;                  // filter button + client-side filtering via pagedVisible
  emptyText: string;                   // shown when the first page is empty (no search)
  installNotice?: string;              // Workshop: shown under the Install button when not installed

  // Fetch one page. The WHOLE filter is passed (replacing the old scalar nsfw/sort args): a
  // server-paged venue (Nexus) reads filter.showNsfw / filter.sortBy exactly as before, while a
  // client-paged venue (Thunderstore) filters and slices its cached catalog. `query` is the
  // debounced search box. `refreshKey` lets a client-paged venue bust its in-memory catalog cache
  // when the user hits "Refresh Catalog" (it changes on refresh); server-paged venues ignore it.
  fetchPage(game: GameStatus, query: string, page: number, filter?: BrowsePagedFilter, refreshKey?: number): Promise<BrowseItem[]>;

  // The inputs that, when changed, must reset to page 1 and re-fetch. Omitted → the component keys on
  // the server-side inputs only (showNsfw + sortBy), preserving Nexus/Workshop behavior. A
  // client-paged venue returns a key over the whole filter so any client-side filter change re-slices.
  fetchKey?(filter?: BrowsePagedFilter): string;

  // The catalog's selectable category list, surfaced to the filter modal (Thunderstore only). Read
  // from the adapter's own cached full catalog; the component bubbles it via onCategories after a fetch.
  categories?(game: GameStatus): string[];

  installedIds(game: GameStatus): Set<string>;
  detail(item: BrowseItem): BrowseDetail;
  uninstallId(game: GameStatus, item: BrowseItem): string; // recorded id used for uninstall + dependents
  install(item: BrowseItem, ctx: InstallContext): void;

  // Installed mods that declare this item as a dependency — surfaced as a warning before uninstall.
  // Omitted → the component matches the recorded dependency id exactly (Nexus/Workshop). Thunderstore
  // overrides because its recorded deps are version-suffixed full_names, which an exact match misses.
  dependents?(game: GameStatus, item: BrowseItem): InstalledMod[];

  // Secondary actions for the selected item in its current install state (e.g. Thunderstore's
  // "Install with options…" when there are resolvable missing deps). Empty / omitted → none. Gets the
  // InstallContext so visibility can be computed against the live in-flight set (ctx.game / .pending /
  // .queuedRefs) — the same data its run() needs — not just (item, installed).
  secondaryActions?(item: BrowseItem, installed: boolean, ctx: InstallContext): BrowseSecondaryAction[];
}
