import { GameStatus } from '../../types';
import { PagedVenueAdapter } from './types';
import { collectionsAdapter } from './collectionsAdapter';

// A game has exactly one browse venue, so its "collections" are whatever that venue calls them —
// Nexus collections today; Thunderstore modpacks (etc.) slot in here later by adding a case. This is
// the single extension point: the Collections tab stays one top-level tab and just lights up for more
// game types as venues gain a collections adapter. No nested Mods|Collections switch needed.
export function collectionsAdapterFor(catalogType: string | undefined): PagedVenueAdapter | null {
  switch (catalogType) {
    case 'nexus':
      return collectionsAdapter;
    // case 'thunderstore': return modpacksAdapter;  // ← future: Thunderstore modpacks
    default:
      return null;
  }
}

// Whether to show the Collections tab for this game (its venue has a collections concept).
export function venueHasCollections(game: GameStatus): boolean {
  return collectionsAdapterFor(game.catalog_type) !== null;
}

// Known initial state of whether a game has any collections, by Steam appid — so the Collections tab
// renders correctly on first paint instead of popping in once the live probe (gameHasCollections)
// returns. The probe is still the source of truth and corrects this if reality differs; a game absent
// here just gets probe-only behavior. Update when a game's collection scene appears/disappears.
export const COLLECTIONS_HINT: Record<number, boolean> = {
  582010: true,    // Monster Hunter: World
  413150: true,    // Stardew Valley
  275850: true,    // No Man's Sky
  1623730: true,   // Palworld
  2050650: true,   // Resident Evil 4
  1446780: true,   // Monster Hunter Rise
  1657630: false,  // Slime Rancher 2 — no collections on Nexus
};
