import { BrowseItem } from './types';

// Filter state for the shared paged Browse tab. The superset of every venue's filter so one filter
// prop drives all of them: Nexus reads showNsfw/sortBy (server-side) + hideLibraries/installed
// (client-side via pagedVisible); Workshop passes no filter; Thunderstore (Phase 2) additionally
// reads showDeprecated/categories, applied in its own fetchPage (NOT pagedVisible). `sortBy` is the
// venue sort key; `hideLibraries` hides framework/library mods (default on).
export interface BrowsePagedFilter {
  installed: boolean;
  notInstalled: boolean;
  showNsfw: boolean;
  sortBy?: string;
  hideLibraries?: boolean;
  showDeprecated?: boolean;   // Thunderstore (Phase 2) client-side; other venues ignore
  categories?: string[];      // Thunderstore (Phase 2) client-side; undefined / [] = all
}

// Apply the client-side paged-browse filters (hide-libraries + install status) to the loaded
// items. Pure so it can be unit-tested in isolation (mirrors installedMatchesFilter).
export function pagedVisible(
  items: BrowseItem[],
  filter: BrowsePagedFilter,
  installedIds: Set<string>,
): BrowseItem[] {
  return items.filter(it => {
    if (filter.hideLibraries && it.isLibrary) return false;
    const inst = installedIds.has(it.installId);
    if (inst && !filter.installed) return false;
    if (!inst && !filter.notInstalled) return false;
    return true;
  });
}
