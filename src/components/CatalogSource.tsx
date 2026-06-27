import { FC } from 'react';

// Where a browse tab's mods come from. Single source of truth for venue credit,
// shown prominently at the top of each browse list.
export type CatalogSourceId = 'thunderstore' | 'bmi' | 'workshop' | 'nexus' | 'ficsit';

const LABELS: Record<CatalogSourceId, string> = {
  thunderstore: 'Mods from Thunderstore',
  bmi: 'Catalog from Balatro Mod Index (skyline69)',
  workshop: 'Mods from the Steam Community Workshop',
  nexus: 'Mods from Nexus Mods',
  ficsit: 'Mods from ficsit.app',
};

export const CatalogSourceLabel: FC<{ source: CatalogSourceId }> = ({ source }) => (
  <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--gpColorTextSecondary)', marginTop: 6 }}>
    {LABELS[source]}
  </div>
);
