import { ButtonItem, DialogCheckbox, Dropdown, ModalRoot } from '@decky/ui';
import { useState, FC, ReactNode } from 'react';

// Nexus sort order. Applied server-side by the v2 GraphQL `mods` query (unlike the
// Thunderstore tab, which sorts the loaded catalog client-side), so changing it re-fetches.
// 'popularity' (endorsements) is the default, matching the Thunderstore tab's "Popularity".
export type NexusSort = 'popularity' | 'downloads' | 'updated' | 'name';
export const NEXUS_SORT_OPTIONS: { data: NexusSort; label: string }[] = [
  { data: 'popularity', label: 'Popularity' },
  { data: 'downloads', label: 'Most downloaded' },
  { data: 'updated', label: 'Recently updated' },
  { data: 'name', label: 'Name (A–Z)' },
];

// Nexus browse is server-paginated and its catalog items only carry name/owner/version/
// date/desc/icon — so unlike the Thunderstore filter there's no deprecated/library/category
// data to filter on. Install status is filtered client-side over the loaded pages; NSFW and
// sort are server-side (toggling either re-fetches), and NSFW is only offered when the
// account-global "Allow NSFW" gate is on.
export interface NexusFilter {
  installed: boolean;
  notInstalled: boolean;
  showNsfw: boolean;
  sortBy: NexusSort;
}

export const defaultNexusFilter: NexusFilter = {
  installed: true,
  notInstalled: true,
  showNsfw: false,
  sortBy: 'popularity',
};

const isDefault = (f: NexusFilter): boolean =>
  f.installed && f.notInstalled && !f.showNsfw && f.sortBy === 'popularity';

const Section: FC<{ title: string; children: ReactNode }> = ({ title, children }) => (
  <div style={{ marginBottom: '12px' }}>
    <div style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.85em', marginBottom: '4px' }}>
      {title}
    </div>
    {children}
  </div>
);

const NexusFilterModal: FC<{
  filter: NexusFilter;
  // Account-global "Allow NSFW" gate (Settings). When off, the Show NSFW control is hidden
  // and adult mods stay excluded server-side; when on, it's offered per-session.
  nsfwEnabled?: boolean;
  onChange: (filter: NexusFilter) => void;
  closeModal?: () => void;
}> = ({ filter, nsfwEnabled = false, onChange, closeModal }) => {
  const [local, setLocal] = useState<NexusFilter>(filter);
  const update = (next: NexusFilter) => { setLocal(next); onChange(next); };

  return (
    <ModalRoot closeModal={closeModal}>
      <div style={{ padding: '16px' }}>
        <div style={{ fontWeight: 'bold', fontSize: '1.1em', marginBottom: '16px' }}>Filter</div>
        <div style={{ marginBottom: '12px' }}>
          <ButtonItem
            layout="below"
            disabled={isDefault(local)}
            onClick={() => update({ ...defaultNexusFilter })}
          >
            Reset Filters
          </ButtonItem>
        </div>
        <Section title="Sort By">
          <Dropdown
            rgOptions={NEXUS_SORT_OPTIONS.map(o => ({ data: o.data, label: o.label }))}
            selectedOption={local.sortBy}
            onChange={(o) => update({ ...local, sortBy: o.data as NexusSort })}
          />
        </Section>
        <Section title="Install Status">
          <DialogCheckbox
            label="Installed"
            checked={local.installed}
            onChange={(v) => update({ ...local, installed: v })}
          />
          <DialogCheckbox
            label="Not Installed"
            checked={local.notInstalled}
            onChange={(v) => update({ ...local, notInstalled: v })}
          />
        </Section>
        {nsfwEnabled ? (
          <Section title="Visibility">
            <DialogCheckbox
              label="Show NSFW"
              checked={local.showNsfw}
              onChange={(v) => update({ ...local, showNsfw: v })}
            />
          </Section>
        ) : (
          <div style={{ marginTop: '8px', color: 'var(--gpColorTextSecondary)', fontSize: '0.75em' }}>
            NSFW mods are hidden. Enable "Allow NSFW content" in Moddy's Settings to show them.
          </div>
        )}
      </div>
    </ModalRoot>
  );
};

export default NexusFilterModal;
