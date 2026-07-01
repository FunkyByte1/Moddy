import { FC } from 'react';

import { CollectionItem, GameStatus } from '../../types';
import CollectionMods from '../../components/CollectionMods';
import { collectionNoun } from './collectionNoun';
import { BrowseItem } from './types';

// The collections adapter's DetailExtra: under a collection/modpack's description, list the mods it
// would install (lazily fetched). Lives in its own .tsx so the adapter stays a plain .ts module.
const CollectionBrowseDetail: FC<{ item: BrowseItem; game: GameStatus }> = ({ item, game }) => {
  const c = item.raw as CollectionItem;
  return (
    <div style={{ marginTop: 4 }}>
      <CollectionMods appid={game.appid} slug={c.slug} noun={collectionNoun(game.catalog_type)} />
    </div>
  );
};

export default CollectionBrowseDetail;
