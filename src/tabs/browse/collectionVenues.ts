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
