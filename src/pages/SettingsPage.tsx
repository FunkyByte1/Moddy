import { ButtonItem, ConfirmModal, Navigation, PanelSection, PanelSectionRow, ToggleField, showModal } from '@decky/ui';
import { FC, useState, useEffect } from 'react';

import {
  getSetting, setSetting, NSFW_ENABLED, NSFW_DEFAULT_ON,
  nexusAccount, nexusLoginStart, nexusLoginWait, nexusLoginCancel, nexusSignOut, NexusAccount,
} from '../lib/api';

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
        // Confirm (A) opts in; Cancel / B backs out without enabling.
        strOKButtonText="Allow"
        strCancelButtonText="Cancel"
        onOK={enable}
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

// A human-readable message for a failed sign-in reason from the backend.
function loginErrorMessage(reason?: string): string {
  switch (reason) {
    case 'port_in_use': return "Couldn't start sign-in — the local port is busy. Close any other sign-in attempt and try again.";
    case 'timeout': return 'Sign-in timed out or was cancelled.';
    case 'exchange_failed': return 'Nexus rejected the sign-in. Please try again.';
    case 'not_configured': return "Nexus sign-in isn't available in this build.";
    case 'access_denied': return 'Sign-in was declined.';
    default: return "Sign-in didn't complete. Please try again.";
  }
}

// Nexus Mods account — account-global sign-in via OAuth2 + PKCE, used by the Nexus Browse
// tab and installs. Replaces the old personal-API-key field: the user signs in through the
// browser (loopback redirect), so no key handling here.
function NexusAccountField() {
  const [account, setAccount] = useState<NexusAccount | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = () => nexusAccount().then(setAccount).catch(() => {});
  useEffect(() => { refresh(); }, []);

  const signIn = async () => {
    setError(null);
    setBusy(true);
    try {
      const start = await nexusLoginStart();
      if (!start.ok || !start.authorize_url) {
        setError(loginErrorMessage(start.reason));
        return;
      }
      // Hand off to the browser; the backend's loopback listener catches the redirect.
      Navigation.NavigateToExternalWeb(start.authorize_url);
      const result = await nexusLoginWait();
      if (result.ok) {
        await refresh();
      } else {
        setError(loginErrorMessage(result.reason));
      }
    } catch {
      setError(loginErrorMessage());
    } finally {
      setBusy(false);
    }
  };

  const cancel = () => { nexusLoginCancel().catch(() => {}); };

  const signOut = () => {
    showModal(
      <ConfirmModal
        strTitle="Sign out of Nexus Mods?"
        strDescription="You'll need to sign in again to browse or install Nexus mods."
        strOKButtonText="Sign out"
        strCancelButtonText="Cancel"
        onOK={async () => { await nexusSignOut(); await refresh(); }}
      />
    );
  };

  // First load (account still null) — render nothing rather than flicker a wrong state.
  if (account === null) return null;

  if (!account.configured) {
    return (
      <PanelSectionRow>
        <div style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.75em' }}>
          Nexus Mods sign-in isn't available in this build.
        </div>
      </PanelSectionRow>
    );
  }

  if (account.signed_in) {
    return (
      <>
        <PanelSectionRow>
          <div style={{ fontSize: '0.9em' }}>
            Signed in to Nexus Mods{account.username ? ` as ${account.username}` : ''}.
          </div>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={signOut}>Sign out</ButtonItem>
        </PanelSectionRow>
      </>
    );
  }

  return (
    <>
      <PanelSectionRow>
        <ButtonItem layout="below" onClick={busy ? cancel : signIn}>
          {busy ? 'Cancel sign-in' : 'Sign in with Nexus Mods'}
        </ButtonItem>
      </PanelSectionRow>
      {busy && (
        <PanelSectionRow>
          <div style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.75em' }}>
            Complete the sign-in in the browser that just opened, then return here.
          </div>
        </PanelSectionRow>
      )}
      {error && (
        <PanelSectionRow>
          <div style={{ color: 'var(--gpColorError, #d33)', fontSize: '0.75em' }}>{error}</div>
        </PanelSectionRow>
      )}
      <PanelSectionRow>
        <div style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.75em' }}>
          Sign in to browse and install Nexus Mods. Downloads use your own Nexus Mods account
          and are subject to Nexus Mods' Terms of Service. Installing mods currently requires a
          Premium account.
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
    <PanelSection title="Nexus Mods account">
      <NexusAccountField />
    </PanelSection>
    <PanelSection title="Content">
      <NsfwToggle />
    </PanelSection>
  </div>
);

export default SettingsPage;
