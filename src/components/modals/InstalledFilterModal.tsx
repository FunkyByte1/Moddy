import { ButtonItem, DialogCheckbox, ModalRoot } from '@decky/ui';
import { useState, FC, ReactNode } from 'react';

import { ModEntry } from '../ModEntry';

export interface InstalledFilter {
  enabled: boolean;
  disabled: boolean;
  onlyUpdates: boolean;
  hideLibraries: boolean;  // hide library/framework mods (default true)
}

export const defaultInstalledFilter: InstalledFilter = {
  enabled: true,
  disabled: true,
  onlyUpdates: false,
  hideLibraries: true,
};

export function installedMatchesFilter(entry: ModEntry, filter: InstalledFilter): boolean {
  if (filter.hideLibraries && entry.isLibrary) return false;
  if (filter.onlyUpdates && !entry.hasUpdate) return false;
  return entry.enabled ? filter.enabled : filter.disabled;
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
  closeModal?: () => void;
}> = ({ filter, onChange, closeModal }) => {
  const [local, setLocal] = useState<InstalledFilter>(filter);
  const update = (next: InstalledFilter) => { setLocal(next); onChange(next); };

  const bothStatuses = local.enabled && local.disabled;

  return (
    <ModalRoot closeModal={closeModal}>
      <div style={{ padding: '16px' }}>
        <div style={{ fontWeight: 'bold', fontSize: '1.1em', marginBottom: '16px' }}>Filter</div>
        <div style={{ marginBottom: '12px' }}>
          <ButtonItem
            layout="below"
            onClick={() => update({ ...local, enabled: !bothStatuses, disabled: !bothStatuses })}
          >
            {bothStatuses ? 'Deselect All' : 'Select All'}
          </ButtonItem>
        </div>
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
        <Section title="Updates">
          <DialogCheckbox
            label="Updates available only"
            checked={local.onlyUpdates}
            onChange={(v) => update({ ...local, onlyUpdates: v })}
          />
        </Section>
        <Section title="Libraries">
          <DialogCheckbox
            label="Show Libraries"
            checked={!local.hideLibraries}
            onChange={(v) => update({ ...local, hideLibraries: !v })}
          />
        </Section>
      </div>
    </ModalRoot>
  );
};

export default InstalledFilterModal;
