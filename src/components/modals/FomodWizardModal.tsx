import { ModalRoot, DialogButton, DialogCheckbox, Dropdown, Focusable } from '@decky/ui';
import { useMemo, useState, FC, ReactNode } from 'react';

import { FomodModel, FomodGroup } from '../../types';
import {
  Selections, gkey, evalWizard, effType, defaultSelections, encodeSelections, isComplete, normalize,
} from '../../lib/fomodWizard';

// The FOMOD install wizard. A scripted-installer mod with real choices parks the install and ships
// its option tree; this lets the user pick (pre-filled to the engine's defaults) and resumes the
// install with the chosen plugin indices. Flag-driven visibility/states are evaluated client-side
// (see lib/fomodWizard); the backend resolve() is the source of truth and force-includes Required /
// drops NotUsable regardless, so this only needs to gather a valid-enough selection.

const NONE = -1; // SelectAtMostOne "(none)" sentinel

const Section: FC<{ title: string; subtitle?: string; children: ReactNode }> = ({ title, subtitle, children }) => (
  <div style={{ marginBottom: '14px' }}>
    <div style={{ fontWeight: 600, fontSize: '0.95em', marginBottom: subtitle ? 0 : '6px' }}>{title}</div>
    {subtitle && <div style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.78em', marginBottom: '6px' }}>{subtitle}</div>}
    {children}
  </div>
);

const FomodWizardModal: FC<{
  model: FomodModel;
  onInstall: (selections: [number, number, number[]][], closeModal: () => void) => void;
  closeModal?: () => void;
}> = ({ model, onInstall, closeModal }) => {
  const close = closeModal ?? (() => {});
  // normalize: fill defaults for visible groups (incl. any a choice reveals) so state matches the
  // controls and the Install button isn't blocked by an "empty" group that's actually showing a pick.
  const [sel, setSel] = useState<Selections>(() => normalize(model, defaultSelections(model)));

  const { visibleSteps, flags } = useMemo(() => evalWizard(model, sel), [model, sel]);
  const complete = useMemo(() => isComplete(model, sel), [model, sel]);

  const setGroup = (si: number, gi: number, plugins: number[]) =>
    setSel(prev => normalize(model, { ...prev, [gkey(si, gi)]: plugins }));

  const renderGroup = (si: number, gi: number, group: FomodGroup) => {
    const key = gkey(si, gi);
    const picked = sel[key] ?? [];
    const usable = group.plugins
      .map((p, pi) => ({ p, pi, t: effType(p, flags) }))
      .filter(x => x.t !== 'NotUsable');

    // Single-pick groups → dropdown (compact, gamepad-friendly even for many variants).
    if (group.type === 'SelectExactlyOne' || group.type === 'SelectAtMostOne') {
      const options = usable.map(x => ({ data: x.pi, label: x.p.name }));
      if (group.type === 'SelectAtMostOne') options.unshift({ data: NONE, label: '(none)' });
      const current = picked.length ? picked[0] : (group.type === 'SelectAtMostOne' ? NONE : (usable[0]?.pi ?? NONE));
      const desc = current !== NONE ? group.plugins[current]?.description : '';
      return (
        <Section title={group.name}>
          <Dropdown
            rgOptions={options}
            selectedOption={current}
            onChange={(o) => setGroup(si, gi, o.data === NONE ? [] : [o.data as number])}
          />
          {desc ? <div style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.78em', marginTop: '4px' }}>{desc}</div> : null}
        </Section>
      );
    }

    // Multi-select groups (Any / AtLeastOne / All) → checkboxes. All = every option forced on.
    const forcedAll = group.type === 'SelectAll';
    return (
      <Section title={group.name}>
        {usable.map(({ p, pi, t }) => {
          const required = forcedAll || t === 'Required';
          const checked = required || picked.includes(pi);
          return (
            <div key={pi} style={{ marginBottom: '2px' }}>
              <DialogCheckbox
                label={p.name}
                description={p.description || undefined}
                checked={checked}
                disabled={required}
                onChange={(v) => setGroup(si, gi, v ? [...picked, pi] : picked.filter(x => x !== pi))}
              />
            </div>
          );
        })}
      </Section>
    );
  };

  return (
    <ModalRoot closeModal={closeModal}>
      <div style={{ padding: '16px', maxHeight: '70vh', display: 'flex', flexDirection: 'column' }}>
        <div style={{ fontWeight: 'bold', fontSize: '1.1em' }}>Configure install</div>
        <div style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.85em', marginBottom: '12px' }}>
          {model.moduleName || 'This mod'} has options — pick what to install (pre-filled to the recommended defaults).
        </div>
        <Focusable style={{ flex: 1, overflowY: 'auto', paddingRight: '4px' }}>
          {visibleSteps.map(si => {
            const step = model.steps[si];
            return (
              <div key={si} style={{ marginBottom: '8px' }}>
                {model.steps.length > 1 && (
                  <div style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.72em', textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: '6px' }}>
                    {step.name}
                  </div>
                )}
                {step.groups.map((g, gi) => renderGroup(si, gi, g))}
              </div>
            );
          })}
        </Focusable>
        <DialogButton
          disabled={!complete}
          style={{ marginTop: '12px' }}
          onClick={() => onInstall(encodeSelections(sel), close)}
        >
          {complete ? 'Install' : 'Make a selection in each required group'}
        </DialogButton>
      </div>
    </ModalRoot>
  );
};

export default FomodWizardModal;
