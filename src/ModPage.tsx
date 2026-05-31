import {
  ButtonItem,
  PanelSection,
  PanelSectionRow,
  ToggleField,
  ConfirmModal,
  showModal,
  Focusable,
} from '@decky/ui';
import { toaster, addEventListener, removeEventListener } from '@decky/api';
import { useState, useEffect, FC } from 'react';

import {
  GameStatus, ModInfo, ModUpdate,
  getSupportedGames, installModloader,
  cancelInstall,
  installMod, uninstallMod, toggleMod,
  getModReleases, getBackedUpVersions, deleteModVersion, checkModUpdates,
  MODLOADER_LAUNCH_OPTIONS, setLaunchOptions,
} from './types';
import FirstLaunchModal from './components/modals/FirstLaunchModal';
import VersionPickerModal from './components/modals/VersionPickerModal';
import DeleteVersionModal from './components/modals/DeleteVersionModal';
import OptionsModal from './components/modals/OptionsModal';

interface ModEntry {
  filename: string;
  name: string;
  installed: boolean;
  enabled: boolean;
  version: string | null;
  hasUpdate: boolean;
  info: ModInfo;
}

// ── Pre-modloader screens ─────────────────────────────────────────────────────

const InstallModloaderScreen: FC<{
  game: GameStatus;
  busy: boolean;
  installing: boolean;
  progress: number;
  onInstall: () => void;
  onCancel: () => void;
}> = ({ game, busy, installing, progress, onInstall, onCancel }) => (
  <Focusable style={{ padding: '16px', paddingBottom: '60px', overflowY: 'auto', height: '100%' }}>
    <h2 style={{ marginBottom: '8px' }}>{game.name}</h2>
    <div style={{ color: 'var(--gpColorTextSecondary)', marginBottom: '20px', lineHeight: '1.5' }}>
      MelonLoader is required to use mods with {game.name}. Install it below to get started.
    </div>
    {installing ? (
      <>
        <div style={{ marginBottom: '4px', fontSize: '0.85em', color: 'var(--gpColorTextSecondary)' }}>
          {`Installing ${game.modloader}... ${progress}%`}
        </div>
        <div style={{ width: '100%', height: '6px', background: 'var(--gpColorBgTertiary)', borderRadius: '3px', marginBottom: '8px' }}>
          <div style={{ width: `${progress}%`, height: '100%', background: 'var(--gpSystemLightBlue)', borderRadius: '3px', transition: 'width 0.2s ease' }} />
        </div>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={onCancel}>Cancel</ButtonItem>
        </PanelSectionRow>
      </>
    ) : (
      <PanelSection>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={onInstall} disabled={busy}>
            {`Install ${game.modloader}`}
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>
    )}
  </Focusable>
);

const FirstLaunchScreen: FC<{
  game: GameStatus;
  onBypass: () => void;
}> = ({ game, onBypass }) => (
  <Focusable style={{ padding: '16px', paddingBottom: '60px', overflowY: 'auto', height: '100%' }}>
    <h2 style={{ marginBottom: '16px' }}>{game.name}</h2>
    <div style={{ padding: '12px', background: 'var(--gpColorBgTertiary)', borderRadius: '4px', marginBottom: '16px', lineHeight: '1.6' }}>
      <div style={{ fontWeight: 'bold', marginBottom: '4px' }}>⚠️ First launch required</div>
      <div>Before installing mods, you need to launch {game.name} once and let it fully load into the game. This may take 2–3 minutes on the first run — do not quit early. Once you have loaded into the game, close it and return here to install mods.</div>
    </div>
    <PanelSection>
      <PanelSectionRow>
        <ButtonItem layout="below" onClick={() => showModal(
          <ConfirmModal
            strTitle="Skip first launch check?"
            strDescription="Installing mods before the first launch may cause them to not work correctly. Only continue if you know what you are doing."
            strOKButtonText="Install anyway"
            strCancelButtonText="Cancel"
            bDestructiveWarning={true}
            onOK={onBypass}
          />
        )}>
          Skip this check
        </ButtonItem>
      </PanelSectionRow>
    </PanelSection>
  </Focusable>
);

// ── Mod detail panel (right column) ──────────────────────────────────────────

const ModDetailPanel: FC<{
  entry: ModEntry;
  busy: boolean;
  installing: boolean;
  progress: number;
  updates: ModUpdate[];
  onInstall: (mod: ModInfo) => void;
  onDelete: (mod: ModInfo) => void;
  onUpdate: (mod: ModInfo) => void;
  onChangeVersion: (mod: ModInfo) => void;
  onCancel: () => void;
  onMenuButton: () => void;
}> = ({ entry, busy, installing, progress, updates, onInstall, onDelete, onUpdate, onChangeVersion, onCancel, onMenuButton }) => {
  const update = updates.find(u => u.filename === entry.filename);

  return (
    <Focusable
      style={{
        flex: 1,
        overflowY: 'auto',
        padding: '12px 16px',
        paddingBottom: '60px',
        display: 'flex',
        flexDirection: 'column',
      }}
      onMenuButton={onMenuButton}
    >
      {/* Installing progress */}
      {installing && (
        <div style={{ marginBottom: '12px' }}>
          <div style={{ marginBottom: '4px', fontSize: '0.85em', color: 'var(--gpColorTextSecondary)' }}>
            {`Installing... ${progress}%`}
          </div>
          <div style={{ width: '100%', height: '6px', background: 'var(--gpColorBgTertiary)', borderRadius: '3px', marginBottom: '6px' }}>
            <div style={{ width: `${progress}%`, height: '100%', background: 'var(--gpSystemLightBlue)', borderRadius: '3px', transition: 'width 0.2s ease' }} />
          </div>
          <ButtonItem layout="below" onClick={onCancel}>Cancel</ButtonItem>
        </div>
      )}

      {/* Thumbnail */}
      {entry.info.thumbnail && (
        <img
          src={entry.info.thumbnail}
          style={{ width: '100%', maxHeight: '150px', objectFit: 'cover', borderRadius: '4px', marginBottom: '12px' }}
        />
      )}

      {/* Name + author */}
      <div style={{ fontWeight: 'bold', fontSize: '1.1em', marginBottom: '4px' }}>{entry.name}</div>
      {entry.info.author && (
        <div style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.85em', marginBottom: '8px' }}>
          by {entry.info.author}
        </div>
      )}

      {/* Version + update */}
      {entry.version && (
        <div style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.85em', marginBottom: '8px' }}>
          Installed: {entry.version}
          {update && (
            <span style={{ color: 'var(--gpSystemLightBlue)', marginLeft: '8px' }}>
              ↑ {update.latest_version} available
            </span>
          )}
        </div>
      )}

      {/* Description */}
      {entry.info.description && (
        <div style={{ lineHeight: '1.5', marginBottom: '12px', color: 'var(--gpColorTextSecondary)', fontSize: '0.9em' }}>
          {entry.info.description}
        </div>
      )}

      {/* Dependencies */}
      {entry.info.dependencies && entry.info.dependencies.length > 0 && (
        <div style={{ fontSize: '0.8em', color: 'var(--gpColorTextSecondary)', marginBottom: '12px' }}>
          Requires: {entry.info.dependencies.map(d => d.replace('.dll', '')).join(', ')}
        </div>
      )}

      {/* Actions */}
      <PanelSection>
        {entry.installed ? (
          <>
            {update && (
              <PanelSectionRow>
                <ButtonItem layout="below" onClick={() => onUpdate(entry.info)} disabled={busy}>
                  {`Update to ${update.latest_version}`}
                </ButtonItem>
              </PanelSectionRow>
            )}
            <PanelSectionRow>
              <ButtonItem layout="below" onClick={() => onChangeVersion(entry.info)} disabled={busy}>
                Change Version
              </ButtonItem>
            </PanelSectionRow>
            <PanelSectionRow>
              <ButtonItem layout="below" onClick={() => onDelete(entry.info)} disabled={busy}>
                Delete
              </ButtonItem>
            </PanelSectionRow>
          </>
        ) : (
          <>
            <PanelSectionRow>
              <ButtonItem layout="below" onClick={() => onInstall(entry.info)} disabled={busy}>
                Install Latest
              </ButtonItem>
            </PanelSectionRow>
            <PanelSectionRow>
              <ButtonItem layout="below" onClick={() => onChangeVersion(entry.info)} disabled={busy}>
                Choose Version
              </ButtonItem>
            </PanelSectionRow>
          </>
        )}
      </PanelSection>
    </Focusable>
  );
};

// ── Mod list item (left column) ───────────────────────────────────────────────

const ModListItem: FC<{
  entry: ModEntry;
  selected: boolean;
  onToggle: (filename: string, enable: boolean) => void;
  onFocus: () => void;
}> = ({ entry, selected, onToggle, onFocus }) => (
  <Focusable
    onFocus={onFocus}
    onActivate={() => {
      if (entry.installed) onToggle(entry.filename, !entry.enabled);
    }}
    style={{
      display: 'flex',
      alignItems: 'center',
      padding: '10px 8px',
      borderRadius: '4px',
      marginBottom: '2px',
      background: selected ? 'var(--gpColorHighlight1)' : 'transparent',
      cursor: 'pointer',
      outline: 'none',
    }}
  >
    <div style={{ flex: 1, minWidth: 0 }}>
      <div style={{
        fontWeight: selected ? 'bold' : 'normal',
        fontSize: '0.9em',
        overflow: 'hidden',
        textOverflow: 'ellipsis',
        whiteSpace: 'nowrap',
      }}>
        {entry.name}
      </div>
      {!entry.installed && (
        <div style={{ fontSize: '0.75em', color: 'var(--gpColorTextSecondary)' }}>
          Not installed
        </div>
      )}
    </div>
    {entry.hasUpdate && (
      <div style={{ color: 'var(--gpSystemLightBlue)', fontSize: '1.1em', marginRight: '4px' }}>↑</div>
    )}
    {entry.installed && (
      <ToggleField
        label=""
        checked={entry.enabled}
        onChange={(val) => onToggle(entry.filename, val)}
      />
    )}
  </Focusable>
);

// ── Main ModPage ──────────────────────────────────────────────────────────────

const ModPage: FC = () => {
  const appid = parseInt(window.location.pathname.split('/').pop() ?? '0');
  const [game, setGame] = useState<GameStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [installing, setInstalling] = useState(false);
  const [progress, setProgress] = useState(0);
  const [modloaderReadyOverride, setModloaderReadyOverride] = useState(false);
  const [updates, setUpdates] = useState<ModUpdate[]>([]);
  const [selectedIndex, setSelectedIndex] = useState(0);

  const refresh = async () => {
    const games = await getSupportedGames();
    const found = games.find(g => g.appid === appid);
    if (found) setGame(found);
  };

  useEffect(() => {
    refresh();
    const listener = addEventListener<[eventAppid: number, percent: number]>(
      'install_progress',
      (eventAppid, percent) => {
        if (eventAppid === appid) setProgress(percent);
      }
    );
    return () => removeEventListener('install_progress', listener);
  }, []);

  if (!game) return <div style={{ padding: '16px' }}>Game not supported or not installed.</div>;

  const installedFilenames = new Set(game.installed_mods.map(m => m.filename));

  // Build unified mod list
  const modEntries: ModEntry[] = game.recommended_mods.map(mod => {
    const installed = game.installed_mods.find(m => m.filename === mod.filename);
    return {
      filename: mod.filename,
      name: mod.name,
      installed: !!installed,
      enabled: installed?.enabled ?? false,
      version: installed?.version ?? null,
      hasUpdate: !!updates.find(u => u.filename === mod.filename),
      info: mod,
    };
  });

  // Add installed mods not in recommended list
  game.installed_mods.forEach(installed => {
    if (!modEntries.find(e => e.filename === installed.filename)) {
      modEntries.push({
        filename: installed.filename,
        name: installed.filename.replace('.dll', ''),
        installed: true,
        enabled: installed.enabled,
        version: installed.version,
        hasUpdate: false,
        info: {
          name: installed.filename.replace('.dll', ''),
          description: '',
          url: '',
          filename: installed.filename,
        },
      });
    }
  });

  const selectedEntry = modEntries[Math.min(selectedIndex, modEntries.length - 1)];

  // ── Handlers ─────────────────────────────────────────────────────────────────

  const handleInstallModloader = async () => {
    setBusy(true);
    setInstalling(true);
    setProgress(0);
    const ok = await installModloader(game.appid);
    setInstalling(false);
    if (ok) {
      const launchOption = MODLOADER_LAUNCH_OPTIONS[game.modloader];
      if (launchOption) setLaunchOptions(game.appid, launchOption);
      await refresh();
      showModal(<FirstLaunchModal gameName={game.name} />);
    } else {
      toaster.toast({ title: 'Decky Mod Manager', body: `Failed to install ${game.modloader}` });
      await refresh();
    }
    setBusy(false);
  };

  const handleCancelInstall = async () => {
    await cancelInstall();
    setInstalling(false);
    setProgress(0);
    setBusy(false);
    toaster.toast({ title: 'Decky Mod Manager', body: 'Installation cancelled' });
  };

  const handleInstallMod = async (mod: ModInfo) => {
    const missingDeps = (mod.dependencies ?? [])
      .filter(dep => !installedFilenames.has(dep))
      .map(dep => game.recommended_mods.find(m => m.filename === dep)?.name ?? dep);

    if (missingDeps.length > 0) {
      showModal(
        <ConfirmModal
          strTitle="Missing dependencies"
          strDescription={`${mod.name} requires: ${missingDeps.join(', ')}. Install dependencies first?`}
          strOKButtonText="Install all & continue"
          strCancelButtonText="Cancel"
          onOK={async () => {
            setBusy(true);
            setInstalling(true);
            setProgress(0);
            for (const depFilename of (mod.dependencies ?? []).filter(d => !installedFilenames.has(d))) {
              const depMod = game.recommended_mods.find(m => m.filename === depFilename);
              if (depMod) {
                const ok = await installMod(game.appid, depMod.filename, null);
                if (!ok) {
                  toaster.toast({ title: 'Decky Mod Manager', body: `Failed to install dependency: ${depMod.name}` });
                  setInstalling(false);
                  setBusy(false);
                  await refresh();
                  return;
                }
              }
            }
            const ok = await installMod(game.appid, mod.filename, null);
            setInstalling(false);
            toaster.toast({ title: 'Decky Mod Manager', body: ok ? `${mod.name} installed` : `Failed to install ${mod.name}` });
            await refresh();
            setBusy(false);
          }}
        />
      );
      return;
    }

    setBusy(true);
    setInstalling(true);
    setProgress(0);
    const ok = await installMod(game.appid, mod.filename, null);
    setInstalling(false);
    toaster.toast({ title: 'Decky Mod Manager', body: ok ? `${mod.name} installed` : `Failed to install ${mod.name}` });
    await refresh();
    setBusy(false);
  };

  const handleDeleteMod = async (mod: ModInfo) => {
    const currentVersion = game.installed_mods.find(m => m.filename === mod.filename)?.version ?? null;
    const backedUp = await getBackedUpVersions(game.appid, mod.filename);

    showModal(
      <DeleteVersionModal
        modName={mod.name}
        currentVersion={currentVersion}
        backedUpVersions={backedUp}
        onDeleteAll={async (close) => {
          close();
          setBusy(true);
          await uninstallMod(game.appid, mod.filename);
          await refresh();
          setBusy(false);
        }}
        onDeleteVersion={async (version, close) => {
          close();
          setBusy(true);
          const isCurrent = currentVersion === version;
          if (isCurrent) {
            // Uninstalling the active version — check for dependents first
            const dependents = game.recommended_mods.filter(m =>
              (m.dependencies ?? []).includes(mod.filename) && installedFilenames.has(m.filename)
            );
            if (dependents.length > 0) {
              const depNames = dependents.map(m => m.name).join(', ');
              showModal(
                <ConfirmModal
                  strTitle="Dependent mods installed"
                  strDescription={`${depNames} depend${dependents.length === 1 ? 's' : ''} on this mod and will stop working. Uninstall all?`}
                  strOKButtonText="Uninstall all"
                  strCancelButtonText="Cancel"
                  bDestructiveWarning={true}
                  onOK={async () => {
                    setBusy(true);
                    for (const dep of dependents) await uninstallMod(game.appid, dep.filename);
                    await uninstallMod(game.appid, mod.filename);
                    await refresh();
                    setBusy(false);
                  }}
                />
              );
              setBusy(false);
              return;
            }
            await uninstallMod(game.appid, mod.filename);
          } else {
            await deleteModVersion(game.appid, mod.filename, version);
          }
          await refresh();
          setBusy(false);
        }}
      />
    );
  };

  const handleToggleMod = async (filename: string, enable: boolean) => {
    setBusy(true);
    await toggleMod(game.appid, filename, enable);
    await refresh();
    setBusy(false);
  };

  const handleUpdateMod = async (mod: ModInfo) => {
    setBusy(true);
    setInstalling(true);
    setProgress(0);
    const ok = await installMod(game.appid, mod.filename, null);
    setInstalling(false);
    if (ok) {
      setUpdates(prev => prev.filter(u => u.filename !== mod.filename));
      toaster.toast({ title: 'Decky Mod Manager', body: `${mod.name} updated` });
    } else {
      toaster.toast({ title: 'Decky Mod Manager', body: `Failed to update ${mod.name}` });
    }
    await refresh();
    setBusy(false);
  };

  const handleInstallModVersion = async (mod: ModInfo, version: string) => {
    const wasInstalled = installedFilenames.has(mod.filename);
    setBusy(true);
    setInstalling(true);
    setProgress(0);
    const ok = await installMod(game.appid, mod.filename, version);
    setInstalling(false);
    if (!wasInstalled) {
      toaster.toast({ title: 'Decky Mod Manager', body: ok ? `${mod.name} installed` : `Failed to install ${mod.name}` });
    } else if (!ok) {
      toaster.toast({ title: 'Decky Mod Manager', body: `Failed to change ${mod.name} to ${version}` });
    }
    await refresh();
    setBusy(false);
  };

  const handleChangeVersion = async (mod: ModInfo) => {
    const releases = await getModReleases(mod.url, mod.filename);
    if (releases.length === 0) {
      toaster.toast({ title: 'Decky Mod Manager', body: 'Could not fetch releases' });
      return;
    }
    const currentVersion = game.installed_mods.find(m => m.filename === mod.filename)?.version ?? null;
    const backedUp = await getBackedUpVersions(game.appid, mod.filename);
    showModal(
      <VersionPickerModal
        mod={mod}
        releases={releases}
        installedVersion={currentVersion}
        backedUpVersions={backedUp}
        onSelect={(version, close) => { close(); handleInstallModVersion(mod, version); }}
      />
    );
  };

  // ── Screen selection ──────────────────────────────────────────────────────────

  if (!game.modloader_installed) {
    return (
      <InstallModloaderScreen
        game={game}
        busy={busy}
        installing={installing}
        progress={progress}
        onInstall={handleInstallModloader}
        onCancel={handleCancelInstall}
      />
    );
  }

  if (!game.modloader_ready && !modloaderReadyOverride) {
    return (
      <FirstLaunchScreen
        game={game}
        onBypass={() => setModloaderReadyOverride(true)}
      />
    );
  }

  // ── Two-column layout ─────────────────────────────────────────────────────────

  const handleOptionsMenu = () => {
    showModal(
      <OptionsModal
        onCheckUpdates={async (close) => {
          close();
          const result = await checkModUpdates(game.appid);
          setUpdates(result);
          if (result.length === 0) {
            toaster.toast({ title: 'Decky Mod Manager', body: 'All mods are up to date' });
          } else {
            toaster.toast({ title: 'Decky Mod Manager', body: `${result.length} update${result.length === 1 ? '' : 's'} available` });
          }
        }}
        onMelonLoaderSettings={(close) => {
          close();
          toaster.toast({ title: 'Decky Mod Manager', body: 'MelonLoader Settings coming soon' });
        }}
      />
    );
  };

  return (
    <Focusable
      style={{ display: 'flex', flexDirection: 'column', height: '100%' }}
      onMenuButton={handleOptionsMenu}
      onMenuActionDescription="Options"
    >
      {/* Header */}
      <div style={{
        padding: '12px 16px 8px',
        fontWeight: 'bold',
        fontSize: '1.1em',
        borderBottom: '1px solid var(--gpColorSeparator)',
        flexShrink: 0,
      }}>
        {game.name}
      </div>

      {/* Two columns */}
      <Focusable style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>

        {/* Left column — mod list (30% width) */}
        <Focusable
          style={{
            width: '30%',
            overflowY: 'auto',
            paddingBottom: '60px',
            borderRight: '1px solid var(--gpColorSeparator)',
            padding: '8px',
          }}
          onMenuButton={handleOptionsMenu}
        >
          {modEntries.length === 0 ? (
            <div style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.85em', padding: '8px' }}>
              No mods available
            </div>
          ) : modEntries.map((entry, i) => (
            <ModListItem
              key={entry.filename}
              entry={entry}
              selected={i === selectedIndex}
              onToggle={handleToggleMod}
              onFocus={() => setSelectedIndex(i)}
            />
          ))}
        </Focusable>

        {/* Right column — mod detail (70% width) */}
        {selectedEntry && (
          <ModDetailPanel
            entry={selectedEntry}
            busy={busy}
            installing={installing}
            progress={progress}
            updates={updates}
            onInstall={handleInstallMod}
            onDelete={handleDeleteMod}
            onUpdate={handleUpdateMod}
            onChangeVersion={handleChangeVersion}
            onCancel={handleCancelInstall}
            onMenuButton={handleOptionsMenu}
          />
        )}
      </Focusable>
    </Focusable>
  );
};

export default ModPage;