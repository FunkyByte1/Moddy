import { ButtonItem, ConfirmModal, PanelSection, PanelSectionRow, TextField, ToggleField, showModal } from '@decky/ui';
import { FC, useState, useEffect, useRef } from 'react';
import { FaEye, FaEyeSlash } from 'react-icons/fa';

import { getSetting, setSetting, NEXUS_API_KEY, NSFW_ENABLED, NSFW_DEFAULT_ON } from './types';

// Account-global gate for NSFW content. Off by default; when on, each game's Browse
// filter gains a "Show NSFW" checkbox (itself off by default) — a deliberate two-step
// before NSFW mods ever appear. A sub-toggle flips that per-game default to on.
function NsfwToggle() {
  const [enabled, setEnabled] = useState(false);
  const [defaultOn, setDefaultOn] = useState(false);

  useEffect(() => {
    getSetting(NSFW_ENABLED).then(v => setEnabled(!!v)).catch(() => {});
    getSetting(NSFW_DEFAULT_ON).then(v => setDefaultOn(!!v)).catch(() => {});
  }, []);

  const enable = () => {
    setEnabled(true);
    setSetting(NSFW_ENABLED, true);
  };

  const onEnabledChange = (next: boolean) => {
    // Turning off is the safe direction — no confirmation. Turning on prompts a one-time
    // acknowledgment of adult content. The ToggleField is controlled by `enabled`, so
    // declining simply leaves it off (we never set state until the user confirms).
    if (!next) {
      setEnabled(false);
      setSetting(NSFW_ENABLED, false);
      return;
    }
    showModal(
      <ConfirmModal
        strTitle="Allow NSFW content?"
        strDescription={
          "This makes adult (18+) mods available in Browse filters. They'll stay hidden " +
          "until you also turn on \"Show NSFW\" in a game's filter."
        }
        // Default-focused button is the safe "Cancel"; the opt-in is the secondary action.
        strOKButtonText="Cancel"
        strCancelButtonText="Allow"
        onCancel={enable}
      />
    );
  };

  const onDefaultChange = (next: boolean) => {
    setDefaultOn(next);
    setSetting(NSFW_DEFAULT_ON, next);
  };

  return (
    <>
      <PanelSectionRow>
        <ToggleField label="Allow NSFW content" checked={enabled} onChange={onEnabledChange} />
      </PanelSectionRow>
      <PanelSectionRow>
        <div style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.75em' }}>
          When on, a "Show NSFW" option appears in each game's Browse filter (off by
          default). While this is off, NSFW mods stay hidden. Applies to the Thunderstore,
          Balatro Mod Index, and Nexus catalogs. Steam Workshop games use Steam's own
          content settings instead.
        </div>
      </PanelSectionRow>
      {enabled && (
        <>
          <PanelSectionRow>
            <ToggleField
              label="Show NSFW by default"
              checked={defaultOn}
              onChange={onDefaultChange}
            />
          </PanelSectionRow>
          <PanelSectionRow>
            <div style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.75em' }}>
              Start each game's Browse filter with NSFW already shown. You can still toggle
              it per game.
            </div>
          </PanelSectionRow>
        </>
      )}
    </>
  );
}

// The Nexus Mods personal API key — account-global, used by the Nexus Browse tab.
function NexusApiKeyField() {
  const [value, setValue] = useState('');
  const [show, setShow] = useState(false);
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    // Populate from the stored key, but NEVER gate the field's enabled state on this load.
    // A previous version disabled the field until the load resolved; when get_setting threw
    // (the settings-module collision) it stayed disabled and unfocusable forever. Keep it
    // always editable, and don't clobber anything the user has already typed.
    getSetting(NEXUS_API_KEY)
      .then(k => { if (typeof k === 'string' && k) setValue(prev => (prev === '' ? k : prev)); })
      .catch(() => {});
    return () => { if (saveTimer.current) clearTimeout(saveTimer.current); };
  }, []);

  const onChange = (next: string) => {
    setValue(next);
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => { setSetting(NEXUS_API_KEY, next.trim()); }, 600);
  };

  return (
    <>
      {/* Decky's bIsPassword is a no-op on current Steam builds, so mask the input
          visually with CSS instead. The real value stays intact (editing/paste work);
          the Show/Hide toggle just flips the masking. */}
      <style>{`.moddy-apikey-mask input { -webkit-text-security: disc !important; }`}</style>
      <PanelSectionRow>
        <div className={show ? undefined : 'moddy-apikey-mask'}>
          <TextField
            label="Nexus Mods API key"
            value={value}
            onChange={e => onChange(e.target.value)}
          />
        </div>
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem layout="below" onClick={() => setShow(s => !s)}>
          {show
            ? <span><FaEyeSlash style={{ marginRight: '6px', verticalAlign: 'middle' }} />Hide key</span>
            : <span><FaEye style={{ marginRight: '6px', verticalAlign: 'middle' }} />Show key</span>}
        </ButtonItem>
      </PanelSectionRow>
      <PanelSectionRow>
        <div style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.75em' }}>
          Generate a personal key at nexusmods.com → Account → API Keys. Premium accounts
          can install; a key is required for browsing.
        </div>
      </PanelSectionRow>
    </>
  );
}

// Full-route settings page reached from the "Settings" button on the Moddy panel. Holds
// account-global config that isn't tied to one game.
const SettingsPage: FC = () => (
  <div style={{
    marginTop: 'var(--basicui-header-height, 40px)',
    height: 'calc(100% - var(--basicui-header-height, 40px))',
    overflowY: 'scroll',
    padding: '8px',
  }}>
    <PanelSection title="Account">
      <NexusApiKeyField />
    </PanelSection>
    <PanelSection title="Content">
      <NsfwToggle />
    </PanelSection>
  </div>
);

export default SettingsPage;
