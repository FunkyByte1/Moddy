import { ButtonItem, DialogCheckbox, ModalRoot } from '@decky/ui';
import { useState, FC, ReactNode } from 'react';

import { ModEntry } from '../ModEntry';

export interface ModFilter {
  installed: boolean;
  notInstalled: boolean;
  enabled: boolean;
  disabled: boolean;
}

export const defaultModFilter: ModFilter = {
  installed: true,
  notInstalled: true,
  enabled: true,
  disabled: true,
};

export function modMatchesFilter(entry: ModEntry, filter: ModFilter): boolean {
  if (!entry.installed) return filter.notInstalled && filter.disabled;
  if (!filter.installed) return false;
  return entry.enabled ? filter.enabled : filter.disabled;
}

const allSelected = (f: ModFilter): boolean =>
  f.installed && f.notInstalled && f.enabled && f.disabled;

const setAllFilters = (value: boolean): ModFilter => ({
  installed: value,
  notInstalled: value,
  enabled: value,
  disabled: value,
});

const Section: FC<{ title: string; children: ReactNode }> = ({ title, children }) => (
  <div style={{ marginBottom: '12px' }}>
    <div style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.85em', marginBottom: '4px' }}>
      {title}
    </div>
    {children}
  </div>
);

const FilterModal: FC<{
  filter: ModFilter;
  onChange: (filter: ModFilter) => void;
  closeModal?: () => void;
}> = ({ filter, onChange, closeModal }) => {
  const [local, setLocal] = useState<ModFilter>(filter);
  const update = (next: ModFilter) => { setLocal(next); onChange(next); };

  return (
    <ModalRoot closeModal={closeModal}>
      <div style={{ padding: '16px' }}>
        <div style={{ fontWeight: 'bold', fontSize: '1.1em', marginBottom: '16px' }}>Filter</div>
        <div style={{ marginBottom: '12px' }}>
          <ButtonItem
            layout="below"
            onClick={() => update(setAllFilters(!allSelected(local)))}
          >
            {allSelected(local) ? 'Deselect All' : 'Select All'}
          </ButtonItem>
        </div>
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
      </div>
    </ModalRoot>
  );
};

export default FilterModal;
