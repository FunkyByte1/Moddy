import {
  ButtonItem,
  PanelSection,
  PanelSectionRow,
  ToggleField,
  showModal,
  Focusable,
} from '@decky/ui';
import { toaster } from '@decky/api';
import { useState, FC } from 'react';

import {
  GameStatus, ModInfo, ModUpdate,
  installMod, uninstallMod, toggleMod,
  getModReleases, getBackedUpVersions, deleteModVersion,
} from '../types';
import VersionPickerModal from '../components/modals/VersionPickerModal';
import DeleteVersionModal from '../components/modals/DeleteVersionModal';
import DependentsModal from '../components/modals/DependentsModal';
import DependencyInstallModal from '../components/modals/DependencyInstallModal';

interface ModEntry {
  id: string;
  name: string;
  installed: boolean;
  enabled: boolean;
  version: string | null;
  hasUpdate: boolean;
  dependenciesMet: boolean;
  info: ModInfo;
}

// ── Mod detail panel (right column) ──────────────────────────────────────────

const ModDetailPanel: FC<{
  entry: ModEntry;
  game: GameStatus;
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
}> = ({ entry, game, busy, installing, progress, updates, onInstall, onDelete, onUpdate, onChangeVersion, onCancel, onMenuButton }) => {
  const update = updates.find(u => u.id === entry.id);

  return (
    <Focusable
      style={{ flex: 1, overflowY: 'auto', padding: '12px 16px', paddingBottom: '60px', display: 'flex', flexDirection: 'column' }}
      onMenuButton={onMenuButton}
      onMenuActionDescription="Options"
    >
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

      {entry.info.thumbnail && (
        <img src={entry.info.thumbnail} style={{ width: '100%', maxHeight: '150px', objectFit: 'cover', borderRadius: '4px', marginBottom: '12px' }} />
      )}

      <div style={{ fontWeight: 'bold', fontSize: '1.1em', marginBottom: '4px' }}>{entry.name}</div>
      {entry.info.author && (
        <div style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.85em', marginBottom: '8px' }}>
          by {entry.info.author}
        </div>
      )}

      {entry.version && (
        <div style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.85em', marginBottom: '8px' }}>
          Installed: {entry.version}
          {update && <span style={{ color: 'var(--gpSystemLightBlue)', marginLeft: '8px' }}>↑ {update.latest_version} available</span>}
        </div>
      )}

      {entry.info.description && (
        <div style={{ lineHeight: '1.5', marginBottom: '12px', color: 'var(--gpColorTextSecondary)', fontSize: '0.9em' }}>
          {entry.info.description}
        </div>
      )}

      {entry.info.dependencies && entry.info.dependencies.length > 0 && (
        <div style={{ fontSize: '0.85em', marginBottom: '12px' }}>
          <div style={{ color: 'var(--gpColorTextSecondary)', marginBottom: '4px' }}>Dependencies:</div>
          {entry.info.dependencies.map(depId => {
            const depInstalled = game.installed_mods.find(m => m.id === depId);
            const depEnabled = depInstalled?.enabled ?? false;
            const depName = game.mods.find(m => m.id === depId)?.name ?? depId;
            return (
              <div key={depId} style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '2px' }}>
                <span style={{ color: depEnabled ? '#5ba85b' : '#f8a623' }}>
                  {depEnabled ? '✓' : depInstalled ? '⚠ disabled' : '⚠ not installed'}
                </span>
                <span style={{ color: 'var(--gpColorTextSecondary)' }}>{depName}</span>
              </div>
            );
          })}
        </div>
      )}

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
  onToggle: (id: string, enable: boolean) => void;
  onFocus: () => void;
}> = ({ entry, selected, onToggle, onFocus }) => (
  <Focusable
    onFocus={onFocus}
    onActivate={() => { if (entry.installed) onToggle(entry.id, !entry.enabled); }}
    style={{
      display: 'flex', alignItems: 'center', padding: '10px 8px',
      borderRadius: '4px', marginBottom: '2px',
      background: selected ? 'var(--gpColorHighlight1)' : 'transparent',
      cursor: 'pointer', outline: 'none',
    }}
  >
    <div style={{ flex: 1, minWidth: 0 }}>
      <div style={{ fontWeight: selected ? 'bold' : 'normal', fontSize: '0.9em', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {entry.name}
      </div>
      {!entry.installed && (
        <div style={{ fontSize: '0.75em', color: 'var(--gpColorTextSecondary)' }}>Not installed</div>
      )}
      {entry.installed && !entry.dependenciesMet && (
        <div style={{ fontSize: '0.75em', color: '#f8a623' }}>⚠ Missing dependency</div>
      )}
    </div>
    {entry.hasUpdate && <div style={{ color: 'var(--gpSystemLightBlue)', fontSize: '1.1em', marginRight: '4px' }}>↑</div>}
    {entry.installed && (
      <ToggleField label="" checked={entry.enabled} onChange={(val) => onToggle(entry.id, val)} />
    )}
  </Focusable>
);

// ── ModsTab ───────────────────────────────────────────────────────────────────

const ModsTab: FC<{
  game: GameStatus;
  onRefresh: () => Promise<void>;
  updates: ModUpdate[];
  setUpdates: (u: ModUpdate[]) => void;
  installing: boolean;
  progress: number;
  setInstalling: (v: boolean) => void;
  setProgress: (v: number) => void;
  onCancel: () => void;
  onMenuButton: () => void;
}> = ({ game, onRefresh, updates, setUpdates, installing, progress, setInstalling, setProgress, onCancel, onMenuButton }) => {
  const [busy, setBusy] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState(0);

  const installedIds = new Set(game.installed_mods.map(m => m.id));

  const modEntries: ModEntry[] = game.mods.map(mod => {
    const installed = game.installed_mods.find(m => m.id === mod.id);
    const dependenciesMet = !installed || !installed.enabled ||
      (mod.dependencies ?? []).every(depId =>
        game.installed_mods.find(m => m.id === depId && m.enabled)
      );
    return {
      id: mod.id,
      name: mod.name,
      installed: !!installed,
      enabled: installed?.enabled ?? false,
      version: installed?.version ?? null,
      hasUpdate: !!updates.find(u => u.id === mod.id),
      dependenciesMet,
      info: mod,
    };
  });

  // Add any installed mods not in the registry
  game.installed_mods.forEach(installed => {
    if (!modEntries.find(e => e.id === installed.id)) {
      modEntries.push({
        id: installed.id,
        name: installed.filename.replace('.dll', ''),
        installed: true,
        enabled: installed.enabled,
        version: installed.version,
        hasUpdate: false,
        dependenciesMet: true,
        info: {
          id: installed.id,
          name: installed.filename.replace('.dll', ''),
          description: '',
          filename: installed.filename,
          source: { type: 'unknown', owner: '', repo: '', asset: '' },
        },
      });
    }
  });

  const selectedEntry = modEntries[Math.min(selectedIndex, modEntries.length - 1)];

  const handleInstallMod = async (mod: ModInfo) => {
    const missingDeps = (mod.dependencies ?? [])
      .filter(depId => !installedIds.has(depId))
      .map(depId => game.mods.find(m => m.id === depId)?.name ?? depId);

    if (missingDeps.length > 0) {
      showModal(
        <DependencyInstallModal
          modName={mod.name}
          dependencyNames={missingDeps}
          onInstall={async (close: () => void) => {
            close();
            setBusy(true); setInstalling(true); setProgress(0);
            for (const depId of (mod.dependencies ?? []).filter(d => !installedIds.has(d))) {
              const depMod = game.mods.find(m => m.id === depId);
              if (depMod) {
                const ok = await installMod(game.appid, depMod.id, null);
                if (ok === null) { setInstalling(false); setBusy(false); await onRefresh(); return; }
                if (!ok) {
                  toaster.toast({ title: 'Moddy', body: `Failed to install dependency: ${depMod.name}` });
                  setInstalling(false); setBusy(false); await onRefresh(); return;
                }
              }
            }
            const ok = await installMod(game.appid, mod.id, null);
            setInstalling(false);
            if (ok === null) { await onRefresh(); setBusy(false); return; }
            toaster.toast({ title: 'Moddy', body: ok ? `${mod.name} installed` : `Failed to install ${mod.name}` });
            await onRefresh(); setBusy(false);
          }}
        />
      );
      return;
    }

    setBusy(true); setInstalling(true); setProgress(0);
    const ok = await installMod(game.appid, mod.id, null);
    setInstalling(false);
    if (ok === null) { await onRefresh(); setBusy(false); return; }
    toaster.toast({ title: 'Moddy', body: ok ? `${mod.name} installed` : `Failed to install ${mod.name}` });
    await onRefresh(); setBusy(false);
  };

  const handleDeleteMod = async (mod: ModInfo) => {
    const currentVersion = game.installed_mods.find(m => m.id === mod.id)?.version ?? null;
    const backedUp = await getBackedUpVersions(game.appid, mod.id);
    const dependents = game.mods.filter(m =>
      (m.dependencies ?? []).includes(mod.id) && installedIds.has(m.id)
    );

    if (dependents.length > 0) {
      showModal(
        <DependentsModal
          dependentNames={dependents.map(m => m.name)}
          onDisable={async (close: () => void) => {
            close(); setBusy(true);
            for (const dep of dependents) await toggleMod(game.appid, dep.id, false);
            await onRefresh(); setBusy(false);
            showModal(
              <DeleteVersionModal
                modName={mod.name}
                currentVersion={currentVersion}
                backedUpVersions={backedUp}
                onDeleteAll={async (c) => { c(); setBusy(true); await uninstallMod(game.appid, mod.id); await onRefresh(); setBusy(false); }}
                onDeleteVersion={async (version, c) => { c(); setBusy(true); if (currentVersion === version) { await uninstallMod(game.appid, mod.id); } else { await deleteModVersion(game.appid, mod.id, version); } await onRefresh(); setBusy(false); }}
              />
            );
          }}
          onIgnore={async (close: () => void) => {
            close();
            showModal(
              <DeleteVersionModal
                modName={mod.name}
                currentVersion={currentVersion}
                backedUpVersions={backedUp}
                onDeleteAll={async (c) => { c(); setBusy(true); await uninstallMod(game.appid, mod.id); await onRefresh(); setBusy(false); }}
                onDeleteVersion={async (version, c) => { c(); setBusy(true); if (currentVersion === version) { await uninstallMod(game.appid, mod.id); } else { await deleteModVersion(game.appid, mod.id, version); } await onRefresh(); setBusy(false); }}
              />
            );
          }}
          onDelete={async (close: () => void) => {
            close(); setBusy(true);
            for (const dep of dependents) await uninstallMod(game.appid, dep.id);
            await uninstallMod(game.appid, mod.id);
            await onRefresh(); setBusy(false);
          }}
        />
      );
      return;
    }

    showModal(
      <DeleteVersionModal
        modName={mod.name}
        currentVersion={currentVersion}
        backedUpVersions={backedUp}
        onDeleteAll={async (close) => { close(); setBusy(true); await uninstallMod(game.appid, mod.id); await onRefresh(); setBusy(false); }}
        onDeleteVersion={async (version, close) => {
          close(); setBusy(true);
          if (currentVersion === version) { await uninstallMod(game.appid, mod.id); }
          else { await deleteModVersion(game.appid, mod.id, version); }
          await onRefresh(); setBusy(false);
        }}
      />
    );
  };

  const handleToggleMod = async (id: string, enable: boolean) => {
    if (enable) {
      // Check if dependencies are installed and enabled
      const mod = game.mods.find(m => m.id === id);
      if (mod) {
        const missingDeps = (mod.dependencies ?? []).filter(depId =>
          !game.installed_mods.find(m => m.id === depId && m.enabled)
        );
        if (missingDeps.length > 0) {
          const missingNames = missingDeps.map(depId => game.mods.find(m => m.id === depId)?.name ?? depId);
          const notInstalled = missingDeps.filter(depId => !game.installed_mods.find(m => m.id === depId));
          const disabled = missingDeps.filter(depId => game.installed_mods.find(m => m.id === depId && !m.enabled));
          showModal(
            <DependencyInstallModal
              modName={mod.name}
              dependencyNames={missingNames}
              actionLabel={notInstalled.length > 0 ? 'Install & Enable' : 'Enable dependencies'}
              onInstall={async (close: () => void) => {
                close(); setBusy(true); setInstalling(true); setProgress(0);
                // Install any not installed
                for (const depId of notInstalled) {
                  const depMod = game.mods.find(m => m.id === depId);
                  if (depMod) {
                    const ok = await installMod(game.appid, depId, null);
                    if (ok === null) { setInstalling(false); setBusy(false); await onRefresh(); return; }
                    if (!ok) {
                      toaster.toast({ title: 'Moddy', body: `Failed to install ${depMod.name}` });
                      setInstalling(false); setBusy(false); await onRefresh(); return;
                    }
                  }
                }
                setInstalling(false);
                // Enable any disabled
                for (const depId of disabled) {
                  await toggleMod(game.appid, depId, true);
                }
                // Now enable the mod itself
                await toggleMod(game.appid, id, true);
                await onRefresh(); setBusy(false);
              }}
            />
          );
          return;
        }
      }
    }

    if (!enable) {
      const dependents = game.mods.filter(m =>
        (m.dependencies ?? []).includes(id) &&
        game.installed_mods.find(im => im.id === m.id && im.enabled)
      );
      if (dependents.length > 0) {
        showModal(
          <DependentsModal
            dependentNames={dependents.map(m => m.name)}
            onDisable={async (close: () => void) => {
              close(); setBusy(true);
              for (const dep of dependents) await toggleMod(game.appid, dep.id, false);
              await toggleMod(game.appid, id, false);
              await onRefresh(); setBusy(false);
            }}
            onIgnore={async (close: () => void) => {
              close(); setBusy(true);
              await toggleMod(game.appid, id, false);
              await onRefresh(); setBusy(false);
            }}
            onDelete={async (close: () => void) => {
              close(); setBusy(true);
              for (const dep of dependents) await uninstallMod(game.appid, dep.id);
              await toggleMod(game.appid, id, false);
              await onRefresh(); setBusy(false);
            }}
          />
        );
        return;
      }
    }
    setBusy(true);
    await toggleMod(game.appid, id, enable);
    await onRefresh(); setBusy(false);
  };

  const handleUpdateMod = async (mod: ModInfo) => {
    setBusy(true); setInstalling(true); setProgress(0);
    const ok = await installMod(game.appid, mod.id, null);
    setInstalling(false);
    if (ok === null) { await onRefresh(); setBusy(false); return; }
    if (ok) {
      setUpdates(updates.filter(u => u.id !== mod.id));
      toaster.toast({ title: 'Moddy', body: `${mod.name} updated` });
    } else {
      toaster.toast({ title: 'Moddy', body: `Failed to update ${mod.name}` });
    }
    await onRefresh(); setBusy(false);
  };

  const handleInstallModVersion = async (mod: ModInfo, version: string) => {
    const wasInstalled = installedIds.has(mod.id);
    setBusy(true); setInstalling(true); setProgress(0);
    const ok = await installMod(game.appid, mod.id, version);
    setInstalling(false);
    if (ok === null) { await onRefresh(); setBusy(false); return; }
    if (!wasInstalled) {
      toaster.toast({ title: 'Moddy', body: ok ? `${mod.name} installed` : `Failed to install ${mod.name}` });
    } else if (!ok) {
      toaster.toast({ title: 'Moddy', body: `Failed to change ${mod.name} to ${version}` });
    }
    await onRefresh(); setBusy(false);
  };

  const handleChangeVersion = async (mod: ModInfo) => {
    const releases = await getModReleases(game.appid, mod.id);
    if (releases.length === 0) { toaster.toast({ title: 'Moddy', body: 'Could not fetch releases' }); return; }
    const currentVersion = game.installed_mods.find(m => m.id === mod.id)?.version ?? null;
    const backedUp = await getBackedUpVersions(game.appid, mod.id);
    showModal(
      <VersionPickerModal
        mod={mod} releases={releases}
        installedVersion={currentVersion} backedUpVersions={backedUp}
        onSelect={(version, close) => { close(); handleInstallModVersion(mod, version); }}
      />
    );
  };

  return (
    <Focusable style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
      <Focusable
        style={{ width: '30%', overflowY: 'auto', paddingBottom: '60px', borderRight: '1px solid var(--gpColorSeparator)', padding: '8px' }}
        onMenuButton={onMenuButton}
        onMenuActionDescription="Options"
      >
        {modEntries.length === 0 ? (
          <div style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.85em', padding: '8px' }}>No mods available</div>
        ) : modEntries.map((entry, i) => (
          <ModListItem key={entry.id} entry={entry} selected={i === selectedIndex}
            onToggle={handleToggleMod} onFocus={() => setSelectedIndex(i)} />
        ))}
      </Focusable>

      {selectedEntry && (
        <ModDetailPanel
          entry={selectedEntry} game={game} busy={busy} installing={installing} progress={progress}
          updates={updates} onInstall={handleInstallMod} onDelete={handleDeleteMod}
          onUpdate={handleUpdateMod} onChangeVersion={handleChangeVersion}
          onCancel={onCancel} onMenuButton={onMenuButton}
        />
      )}
    </Focusable>
  );
};

export default ModsTab;