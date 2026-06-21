import { BrowseItem } from './types';

// Filter state for the shared paged Browse tab (Nexus). Workshop passes no filter.
// `sortBy` is the Nexus sort key; `hideLibraries` hides framework/library mods (default on).
export interface BrowsePagedFilter {
  installed: boolean;
  notInstalled: boolean;
  showNsfw: boolean;
  sortBy?: string;
  hideLibraries?: boolean;
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
