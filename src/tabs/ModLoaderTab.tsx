import {
  ButtonItem,
  PanelSection,
  PanelSectionRow,
  ToggleField,
  ConfirmModal,
  ModalRoot,
  showModal,
  Focusable,
} from '@decky/ui';
import { toaster, addEventListener, removeEventListener } from '@decky/api';
import { useState, useEffect, FC } from 'react';

import {
  GameStatus, ModRelease, ModloaderUpdate,
  installModloader, uninstallModloader, enableModloader, disableModloader,
  cancelInstall, getModloaderVersion, getModloaderReleases, checkModloaderUpdate,
  addModloaderLaunchOptions, removeModloaderLaunchOptions,
} from '../types';
import FirstLaunchModal from '../components/modals/FirstLaunchModal';
import { SHOW_VERSION_OPTIONS } from '../featureFlags';

// Version picker for modloader
const ModloaderVersionPickerModal: FC<{
  modloader: string;
  releases: ModRelease[];
  installedVersion: string | null;
  onSelect: (version: string, closeModal: () => void) => void;
  closeModal?: () => void;
}> = ({ modloader, releases, installedVersion, onSelect, closeModal }) => (
  <ModalRoot closeModal={closeModal}>
    <div style={{ padding: '16px' }}>
      <div style={{ fontWeight: 'bold', fontSize: '1.1em', marginBottom: '12px' }}>
        Choose version — {modloader}
      </div>
      {releases.map(release => (
        <div key={release.version} style={{ marginBottom: '8px' }}>
          <ButtonItem layout="below" onClick={() => onSelect(release.version, closeModal ?? (() => {}))}>
            <div style={{ display: 'flex', justifyContent: 'space-between', width: '100%' }}>
              <span>
                {release.version}
                {release.published_at ? ` (${release.published_at.split('T')[0]})` : ''}
              </span>
              {installedVersion === release.version && (
                <span style={{ color: 'var(--gpSystemLightBlue)', fontSize: '0.85em' }}>✓ current</span>
              )}
            </div>
          </ButtonItem>
        </div>
      ))}
    </div>
  </ModalRoot>
);

const ModLoaderTab: FC<{
  game: GameStatus;
  onRefresh: () => Promise<void>;
  onModloaderReady: () => void;
  setInstalling: (v: boolean) => void;
}> = ({ game, onRefresh, onModloaderReady, setInstalling }) => {
  const [busy, setBusy] = useState(false);
  const [localInstalling, setLocalInstalling] = useState(false);
  const [progress, setProgress] = useState(0);
  const [installedVersion, setInstalledVersion] = useState<string | null>(null);
  const [modloaderUpdate, setModloaderUpdate] = useState<ModloaderUpdate | null>(null);
  const [checkingUpdate, setCheckingUpdate] = useState(false);

  const bundled = game.modloader_bundled ?? [];
  const bundledText = bundled.join(' and ');

  const loadVersion = async () => {
    const v = await getModloaderVersion(game.appid);
    setInstalledVersion(v);
  };

  useEffect(() => {
    if (game.modloader_installed) loadVersion();
    const listener = addEventListener<[eventAppid: number, percent: number]>(
      'install_progress',
      (eventAppid, percent) => {
        if (eventAppid === game.appid) setProgress(percent);
      }
    );
    return () => removeEventListener('install_progress', listener);
  }, [game.modloader_installed]);

  const handleInstall = async (version: string | null = null) => {
    setBusy(true);
    setLocalInstalling(true);
    setInstalling(true);
    setProgress(0);
    const ok = await installModloader(game.appid, version);
    setLocalInstalling(false);
    setInstalling(false);
    if (ok) {
      if (game.modloader_launch_options) addModloaderLaunchOptions(game.appid, game.modloader_launch_options);
      await onRefresh();
      await loadVersion();
      if (game.modloader_needs_first_launch) {
        showModal(<FirstLaunchModal gameName={game.name} modloaderName={game.modloader_name} />);
      }
    } else {
      toaster.toast({ title: 'Moddy', body: `Failed to install ${game.modloader_name}` });
    }
    setBusy(false);
  };

  const handleCancel = async () => {
    await cancelInstall();
    setLocalInstalling(false);
    setInstalling(false);
    setProgress(0);
    setBusy(false);
  };

  const handleUninstall = async () => {
    showModal(
      <ConfirmModal
        strTitle={`Uninstall ${game.modloader}?`}
        strDescription="This will remove the mod loader. All mods will stop working until it is reinstalled."
        strOKButtonText="Cancel"
        strCancelButtonText="Uninstall"
        onCancel={async () => {
          setBusy(true);
          const ok = await uninstallModloader(game.appid);
          if (ok) {
            removeModloaderLaunchOptions(game.appid, game.modloader_launch_options);
            setInstalledVersion(null);
            setModloaderUpdate(null);
            toaster.toast({ title: 'Moddy', body: `${game.modloader_name} uninstalled` });
          } else {
            toaster.toast({ title: 'Moddy', body: `Failed to uninstall ${game.modloader_name}` });
          }
          await onRefresh();
          setBusy(false);
        }}
      />
    );
  };

  const handleToggle = async (enable: boolean) => {
    setBusy(true);
    const ok = enable ? await enableModloader(game.appid) : await disableModloader(game.appid);
    if (ok) {
      if (game.modloader_launch_options) {
        if (enable) addModloaderLaunchOptions(game.appid, game.modloader_launch_options);
        else removeModloaderLaunchOptions(game.appid, game.modloader_launch_options);
      }
    } else {
      toaster.toast({ title: 'Moddy', body: `Failed to ${enable ? 'enable' : 'disable'} ${game.modloader_name}` });
    }
    await onRefresh();
    setBusy(false);
  };

  const handleCheckUpdate = async () => {
    setCheckingUpdate(true);
    const update = await checkModloaderUpdate(game.appid);
    setModloaderUpdate(update);
    setCheckingUpdate(false);
    if (!update) {
      toaster.toast({ title: 'Moddy', body: `${game.modloader} is up to date` });
    }
  };

  const handleChangeVersion = async () => {
    const releases = await getModloaderReleases(game.appid);
    if (releases.length === 0) {
      toaster.toast({ title: 'Moddy', body: 'Could not fetch releases' });
      return;
    }
    showModal(
      <ModloaderVersionPickerModal
        modloader={game.modloader_name}
        releases={releases}
        installedVersion={installedVersion}
        onSelect={(version, close) => { close(); handleInstall(version); }}
      />
    );
  };

  return (
    <Focusable
      style={{ padding: '16px', paddingBottom: '60px', overflowY: 'auto', height: '100%' }}
      onMenuActionDescription="Options"
    >

      {/* Progress bar */}
      {localInstalling && (
        <div style={{ marginBottom: '16px' }}>
          <div style={{ marginBottom: '4px', fontSize: '0.85em', color: 'var(--gpColorTextSecondary)' }}>
            {`Installing ${game.modloader_name}... ${progress}%`}
          </div>
          <div style={{ width: '100%', height: '6px', background: 'var(--gpColorBgTertiary)', borderRadius: '3px', marginBottom: '8px' }}>
            <div style={{ width: `${progress}%`, height: '100%', background: 'var(--gpSystemLightBlue)', borderRadius: '3px', transition: 'width 0.2s ease' }} />
          </div>
          <PanelSectionRow>
            <ButtonItem layout="below" onClick={handleCancel}>Cancel</ButtonItem>
          </PanelSectionRow>
        </div>
      )}

      {!game.modloader_installed ? (
        // ── Not installed ──────────────────────────────────────────────────────
        <PanelSection title={game.modloader_name}>
          <PanelSectionRow>
            <div style={{ color: 'var(--gpColorTextSecondary)', lineHeight: '1.5', marginBottom: '12px' }}>
              {game.modloader_name} is required to use mods with {game.name}. Install it below to get started.
              {bundledText && ` ${bundledText}, required by nearly every mod, is installed automatically alongside it.`}
            </div>
          </PanelSectionRow>
          <PanelSectionRow>
            <ButtonItem layout="below" onClick={() => handleInstall(null)} disabled={busy}>
              Install Latest
            </ButtonItem>
          </PanelSectionRow>
          {SHOW_VERSION_OPTIONS && (
            <PanelSectionRow>
              <ButtonItem layout="below" onClick={handleChangeVersion} disabled={busy}>
                Choose Version
              </ButtonItem>
            </PanelSectionRow>
          )}
        </PanelSection>
      ) : (
        // ── Installed (ready or not) ───────────────────────────────────────────
        <>
          {/* First launch warning — shown as a section when not yet ready */}
          {!game.modloader_ready && (
            <PanelSection title="⚠️ First Launch Required">
              <PanelSectionRow>
                <div style={{ color: 'var(--gpColorTextSecondary)', lineHeight: '1.5', marginBottom: '8px', fontSize: '0.9em' }}>
                  Launch {game.name} once and let it fully load before installing mods. This may take 2–3 minutes.
                </div>
              </PanelSectionRow>
              <PanelSectionRow>
                <ButtonItem layout="below" onClick={() => showModal(
                  <ConfirmModal
                    strTitle="Skip first launch check?"
                    strDescription="Installing mods before the first launch may cause them to not work correctly. Only continue if you know what you are doing."
                    strOKButtonText="Cancel"
                    strCancelButtonText="Install anyway"
                    onCancel={onModloaderReady}
                  />
                )}>
                  Skip this check
                </ButtonItem>
              </PanelSectionRow>
            </PanelSection>
          )}

          <PanelSection title={game.modloader_name}>
            <PanelSectionRow>
              <div style={{ fontSize: '0.9em', marginBottom: '4px' }}>
                <span style={{ color: 'var(--gpColorTextSecondary)' }}>Version: </span>
                <span>{installedVersion ?? 'Unknown'}</span>
                {modloaderUpdate && (
                  <span style={{ color: 'var(--gpSystemLightBlue)', marginLeft: '8px' }}>
                    ↑ {modloaderUpdate.latest} available
                  </span>
                )}
              </div>
            </PanelSectionRow>
            {bundledText && (
              <PanelSectionRow>
                <div style={{ fontSize: '0.9em', marginBottom: '4px' }}>
                  <span style={{ color: 'var(--gpColorTextSecondary)' }}>Includes: </span>
                  <span>{bundledText}</span>
                </div>
              </PanelSectionRow>
            )}
            <PanelSectionRow>
              <ToggleField
                label={game.modloader_enabled ? 'Enabled' : 'Disabled'}
                checked={game.modloader_enabled}
                onChange={handleToggle}
                disabled={busy}
              />
            </PanelSectionRow>
          </PanelSection>

          <PanelSection title="Version Management">
            {modloaderUpdate && (
              <PanelSectionRow>
                <ButtonItem layout="below" onClick={() => handleInstall(null)} disabled={busy}>
                  {`Update to ${modloaderUpdate.latest}`}
                </ButtonItem>
              </PanelSectionRow>
            )}
            {SHOW_VERSION_OPTIONS && (
              <PanelSectionRow>
                <ButtonItem layout="below" onClick={handleChangeVersion} disabled={busy}>
                  Change Version
                </ButtonItem>
              </PanelSectionRow>
            )}
            <PanelSectionRow>
              <ButtonItem layout="below" onClick={handleCheckUpdate} disabled={busy || checkingUpdate}>
                {checkingUpdate ? 'Checking...' : 'Check for Updates'}
              </ButtonItem>
            </PanelSectionRow>
          </PanelSection>

          <PanelSection title="Danger Zone">
            <PanelSectionRow>
              <ButtonItem layout="below" onClick={handleUninstall} disabled={busy}>
                Uninstall {game.modloader_name}
              </ButtonItem>
            </PanelSectionRow>
          </PanelSection>
        </>
      )}
    </Focusable>
  );
};

export default ModLoaderTab;