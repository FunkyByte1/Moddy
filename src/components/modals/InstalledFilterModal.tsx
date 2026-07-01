import { ButtonItem, DialogCheckbox, Dropdown, ModalRoot } from '@decky/ui';
import { useState, FC, ReactNode } from 'react';

import { ModEntry } from '../ModEntry';
import { InstalledCollection, collectionSources } from '../../lib/modSources';
import { CollectionNoun } from '../../tabs/browse/collectionVenues';

// Installed-list ordering. 'name' (alphabetical) is the default — it's stable and works for
// every mod, including ones installed before install timestamps were recorded.
export type InstalledSort = 'name' | 'recent' | 'enabled' | 'updates';
export const INSTALLED_SORT_OPTIONS: { data: InstalledSort; label: string }[] = [
  { data: 'name', label: 'Name (A–Z)' },
  { data: 'recent', label: 'Recently downloaded' },
  { data: 'enabled', label: 'Enabled first' },
  { data: 'updates', label: 'Updates first' },
];

export interface InstalledFilter {
  enabled: boolean;
  disabled: boolean;
  onlyUpdates: boolean;
  hideLibraries: boolean;  // hide library/framework mods (default true)
  sortBy: InstalledSort;
  hiddenCollections: string[];     // collection slugs whose (exclusively-owned) mods are hidden
  showCollectionEntries: boolean;  // show the Collections group rows at the top of the list (default true)
}

export const defaultInstalledFilter: InstalledFilter = {
  enabled: true,
  disabled: true,
  onlyUpdates: false,
  hideLibraries: true,
  sortBy: 'name',
  hiddenCollections: [],
  showCollectionEntries: true,
};

export function installedMatchesFilter(entry: ModEntry, filter: InstalledFilter): boolean {
  if (filter.hideLibraries && entry.isLibrary) return false;
  if (filter.onlyUpdates && !entry.hasUpdate) return false;
  // Per-collection visibility: hide a mod only when EVERY collection it came from is hidden AND it
  // has no other reason to be listed (no manual install, no shown collection) — so hiding a collection
  // never hides a mod you also installed yourself or that another (shown) collection brought in.
  if (filter.hiddenCollections?.length) {
    const cols = collectionSources(entry.sources);
    if (cols.length > 0) {
      const hidden = new Set(filter.hiddenCollections);
      const hasShownCollection = cols.some(c => !hidden.has(c.slug));
      const hasManual = !!entry.sources && 'manual' in entry.sources;
      if (!hasShownCollection && !hasManual) return false;
    }
  }
  return entry.enabled ? filter.enabled : filter.disabled;
}

// Order installed entries for display. Name is the tiebreaker everywhere so the result is
// deterministic within a group and among legacy mods with no recorded install time. Returns
// a new array (never mutates the input).
export function sortInstalledEntries(entries: ModEntry[], sortBy: InstalledSort): ModEntry[] {
  const byName = (a: ModEntry, b: ModEntry) =>
    a.name.localeCompare(b.name, undefined, { sensitivity: 'base' });
  const sorted = [...entries];
  switch (sortBy) {
    // Newest install first; mods with no recorded time (legacy/untracked, addedAt 0) fall to
    // the bottom, alphabetical among themselves.
    case 'recent':
      sorted.sort((a, b) => (b.addedAt - a.addedAt) || byName(a, b));
      break;
    case 'enabled':
      sorted.sort((a, b) => (Number(b.enabled) - Number(a.enabled)) || byName(a, b));
      break;
    case 'updates':
      sorted.sort((a, b) => (Number(b.hasUpdate) - Number(a.hasUpdate)) || byName(a, b));
      break;
    case 'name':
    default:
      sorted.sort(byName);
  }
  return sorted;
}

const Section: FC<{ title: string; children: ReactNode }> = ({ title, children }) => (
  <div style={{ marginBottom: '12px' }}>
    <div style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.85em', marginBottom: '4px' }}>
      {title}
    </div>
    {children}
  </div>
);

const InstalledFilterModal: FC<{
  filter: InstalledFilter;
  onChange: (filter: InstalledFilter) => void;
  collections?: InstalledCollection[];  // installed collections, for the per-collection show/hide toggles
  noun?: CollectionNoun;                // the venue's word for the set ("modpack" / "collection")
  closeModal?: () => void;
}> = ({ filter, onChange, collections, noun, closeModal }) => {
  const cn = noun ?? { one: 'collection', many: 'Collections' };
  const [local, setLocal] = useState<InstalledFilter>(filter);
  const update = (next: InstalledFilter) => { setLocal(next); onChange(next); };

  const allOn = local.enabled && local.disabled && local.hideLibraries;

  return (
    <ModalRoot closeModal={closeModal}>
      <div style={{ padding: '16px' }}>
        <div style={{ fontWeight: 'bold', fontSize: '1.1em', marginBottom: '16px' }}>Filter</div>
        <div style={{ marginBottom: '12px' }}>
          <ButtonItem
            layout="below"
            onClick={() => update({ ...local, enabled: !allOn, disabled: !allOn, hideLibraries: !allOn })}
          >
            {allOn ? 'Deselect All' : 'Select All'}
          </ButtonItem>
        </div>
        <Section title="Sort By">
          <Dropdown
            rgOptions={INSTALLED_SORT_OPTIONS.map(o => ({ data: o.data, label: o.label }))}
            selectedOption={local.sortBy}
            onChange={(o) => update({ ...local, sortBy: o.data as InstalledSort })}
          />
        </Section>
        <Section title="Enabled Status">
          <DialogCheckbox
            label="Enabled"
            checked={local.enabled}
            onChange={(v) => update({ ...local, enabled: v })}
          />
          <DialogCheckbox
            label="Disabled"
            checked={local.disabled}
            onChange={(v) => update({ ...local, disabled: v })}
          />
        </Section>
        {collections && collections.length > 0 && (
          <Section title={cn.many}>
            <DialogCheckbox
              label={`Show ${cn.one} groups`}
              checked={local.showCollectionEntries}
              onChange={(v) => update({ ...local, showCollectionEntries: v })}
            />
            {collections.map((c) => {
              const shown = !local.hiddenCollections.includes(c.slug);
              return (
                <DialogCheckbox
                  key={c.slug}
                  label={`Show mods from ${c.name}`}
                  checked={shown}
                  onChange={(v) => update({
                    ...local,
                    hiddenCollections: v
                      ? local.hiddenCollections.filter((s) => s !== c.slug)
                      : [...local.hiddenCollections, c.slug],
                  })}
                />
              );
            })}
          </Section>
        )}
        <Section title="Misc">
          <DialogCheckbox
            label="Updates available only"
            checked={local.onlyUpdates}
            onChange={(v) => update({ ...local, onlyUpdates: v })}
          />
          <DialogCheckbox
            label="Hide Libraries"
            checked={local.hideLibraries}
            onChange={(v) => update({ ...local, hideLibraries: v })}
          />
        </Section>
      </div>
    </ModalRoot>
  );
};

export default InstalledFilterModal;
