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
  MODLOADER_LAUNCH_OPTIONS, setLaunchOptions,
} from '../types';
import FirstLaunchModal from '../components/modals/FirstLaunchModal';

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
      const launchOption = MODLOADER_LAUNCH_OPTIONS[game.modloader];
      if (launchOption) setLaunchOptions(game.appid, launchOption);
      await onRefresh();
      await loadVersion();
      showModal(<FirstLaunchModal gameName={game.name} />);
    } else {
      toaster.toast({ title: 'Moddy', body: `Failed to install ${game.modloader}` });
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
            setLaunchOptions(game.appid, '');
            setInstalledVersion(null);
            setModloaderUpdate(null);
            toaster.toast({ title: 'Moddy', body: `${game.modloader} uninstalled` });
          } else {
            toaster.toast({ title: 'Moddy', body: `Failed to uninstall ${game.modloader}` });
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
      const launchOption = MODLOADER_LAUNCH_OPTIONS[game.modloader];
      if (launchOption) setLaunchOptions(game.appid, enable ? launchOption : '');
    } else {
      toaster.toast({ title: 'Moddy', body: `Failed to ${enable ? 'enable' : 'disable'} ${game.modloader}` });
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
        modloader={game.modloader}
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
            {`Installing ${game.modloader}... ${progress}%`}
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
        <PanelSection title="MelonLoader">
          <PanelSectionRow>
            <div style={{ color: 'var(--gpColorTextSecondary)', lineHeight: '1.5', marginBottom: '12px' }}>
              MelonLoader is required to use mods with {game.name}. Install it below to get started.
            </div>
          </PanelSectionRow>
          <PanelSectionRow>
            <ButtonItem layout="below" onClick={() => handleInstall(null)} disabled={busy}>
              Install Latest
            </ButtonItem>
          </PanelSectionRow>
          <PanelSectionRow>
            <ButtonItem layout="below" onClick={handleChangeVersion} disabled={busy}>
              Choose Version
            </ButtonItem>
          </PanelSectionRow>
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

          <PanelSection title="MelonLoader">
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
            <PanelSectionRow>
              <ButtonItem layout="below" onClick={handleChangeVersion} disabled={busy}>
                Change Version
              </ButtonItem>
            </PanelSectionRow>
            <PanelSectionRow>
              <ButtonItem layout="below" onClick={handleCheckUpdate} disabled={busy || checkingUpdate}>
                {checkingUpdate ? 'Checking...' : 'Check for Updates'}
              </ButtonItem>
            </PanelSectionRow>
          </PanelSection>

          <PanelSection title="Danger Zone">
            <PanelSectionRow>
              <ButtonItem layout="below" onClick={handleUninstall} disabled={busy}>
                Uninstall MelonLoader
              </ButtonItem>
            </PanelSectionRow>
          </PanelSection>
        </>
      )}
    </Focusable>
  );
};

export default ModLoaderTab;