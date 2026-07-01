// The user-facing noun for a venue's curated sets — Thunderstore calls them "modpacks", Nexus
// "collections". A game has exactly one Browse venue, so the noun is a pure function of its catalog
// type; it's threaded into the Collections tab title and every Installed/Browse label so the same
// components serve both venues. Kept in its own leaf module (no other local imports) so the components
// the collections adapter pulls in can use it without forming an import cycle through collectionVenues.
export interface CollectionNoun { one: string; many: string; }

export function collectionNoun(catalogType: string | undefined): CollectionNoun {
  return catalogType === 'thunderstore'
    ? { one: 'modpack', many: 'Modpacks' }
    : { one: 'collection', many: 'Collections' };
}
