import { ButtonItem, DialogCheckbox, ModalRoot } from '@decky/ui';
import { useState, FC, ReactNode } from 'react';

export interface BrowseFilter {
  installed: boolean;
  notInstalled: boolean;
  showDeprecated: boolean;
  showNsfw: boolean;
  categories: string[]; // selected categories; empty = all categories
}

export const defaultBrowseFilter: BrowseFilter = {
  installed: true,
  notInstalled: true,
  showDeprecated: false,
  showNsfw: false,
  categories: [],
};

const isDefault = (f: BrowseFilter): boolean =>
  f.installed && f.notInstalled && !f.showDeprecated && !f.showNsfw && f.categories.length === 0;

const Section: FC<{ title: string; children: ReactNode }> = ({ title, children }) => (
  <div style={{ marginBottom: '12px' }}>
    <div style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.85em', marginBottom: '4px' }}>
      {title}
    </div>
    {children}
  </div>
);

const BrowseFilterModal: FC<{
  filter: BrowseFilter;
  categories: string[];
  onChange: (filter: BrowseFilter) => void;
  closeModal?: () => void;
}> = ({ filter, categories, onChange, closeModal }) => {
  const [local, setLocal] = useState<BrowseFilter>(filter);
  const update = (next: BrowseFilter) => { setLocal(next); onChange(next); };

  // Empty `categories` means "all" — every box reads as checked. Unchecking one
  // expands the empty set to "all except this"; re-checking until every category
  // is present collapses back to empty so the filter stays off.
  const allSelected = local.categories.length === 0;
  const catChecked = (cat: string) => allSelected || local.categories.includes(cat);
  const toggleCategory = (cat: string, v: boolean) => {
    let sel = allSelected ? [...categories] : [...local.categories];
    if (v) { if (!sel.includes(cat)) sel.push(cat); }
    else { sel = sel.filter(c => c !== cat); }
    if (sel.length === categories.length) sel = [];
    update({ ...local, categories: sel });
  };

  return (
    <ModalRoot closeModal={closeModal}>
      <div style={{ padding: '16px' }}>
        <div style={{ fontWeight: 'bold', fontSize: '1.1em', marginBottom: '16px' }}>Filter</div>
        <div style={{ marginBottom: '12px' }}>
          <ButtonItem
            layout="below"
            disabled={isDefault(local)}
            onClick={() => update({ ...defaultBrowseFilter })}
          >
            Reset Filters
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
        <Section title="Visibility">
          <DialogCheckbox
            label="Show Deprecated"
            checked={local.showDeprecated}
            onChange={(v) => update({ ...local, showDeprecated: v })}
          />
          <DialogCheckbox
            label="Show NSFW"
            checked={local.showNsfw}
            onChange={(v) => update({ ...local, showNsfw: v })}
          />
        </Section>
        {categories.length > 0 && (
          <Section title="Categories">
            <div style={{ maxHeight: '220px', overflowY: 'auto' }}>
              {categories.map(cat => (
                <DialogCheckbox
                  key={cat}
                  label={cat}
                  checked={catChecked(cat)}
                  onChange={(v) => toggleCategory(cat, v)}
                />
              ))}
            </div>
          </Section>
        )}
      </div>
    </ModalRoot>
  );
};

export default BrowseFilterModal;
