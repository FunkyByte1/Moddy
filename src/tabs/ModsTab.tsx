import { showModal, Focusable } from '@decky/ui';
import { toaster } from '@decky/api';
import { useState, FC } from 'react';

import {
  GameStatus, ModInfo, ModUpdate,
  installMod, uninstallMod, toggleMod,
  getModReleases, getBackedUpVersions, deleteModVersion,
} from '../types';
import { ModEntry } from '../components/ModEntry';
import ModDetailPanel from '../components/ModDetailPanel';
import ModListItem from '../components/ModListItem';
import VersionPickerModal from '../components/modals/VersionPickerModal';
import DeleteVersionModal from '../components/modals/DeleteVersionModal';
import DependentsModal from '../components/modals/DependentsModal';
import DependencyInstallModal from '../components/modals/DependencyInstallModal';

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
      id: mod.id, name: mod.name,
      installed: !!installed, enabled: installed?.enabled ?? false,
      version: installed?.version ?? null,
      hasUpdate: !!updates.find(u => u.id === mod.id),
      dependenciesMet, info: mod,
    };
  });

  game.installed_mods.forEach(installed => {
    if (!modEntries.find(e => e.id === installed.id)) {
      modEntries.push({
        id: installed.id, name: installed.filename.replace('.dll', ''),
        installed: true, enabled: installed.enabled, version: installed.version,
        hasUpdate: false, dependenciesMet: true,
        info: { id: installed.id, name: installed.filename.replace('.dll', ''), description: '', filename: installed.filename, source: { type: 'unknown', owner: '', repo: '', asset: '' } },
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
            close(); setBusy(true); setInstalling(true); setProgress(0);
            for (const depId of (mod.dependencies ?? []).filter(d => !installedIds.has(d))) {
              const depMod = game.mods.find(m => m.id === depId);
              if (depMod) {
                const ok = await installMod(game.appid, depMod.id, null);
                if (ok === null) { setInstalling(false); setBusy(false); await onRefresh(); return; }
                if (!ok) { toaster.toast({ title: 'Moddy', body: `Failed to install dependency: ${depMod.name}` }); setInstalling(false); setBusy(false); await onRefresh(); return; }
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
    const dependents = game.mods.filter(m => (m.dependencies ?? []).includes(mod.id) && installedIds.has(m.id));

    const showDeleteModal = () => showModal(
      <DeleteVersionModal
        modName={mod.name} currentVersion={currentVersion} backedUpVersions={backedUp}
        onDeleteAll={async (c) => { c(); setBusy(true); await uninstallMod(game.appid, mod.id); await onRefresh(); setBusy(false); }}
        onDeleteVersion={async (version, c) => { c(); setBusy(true); if (currentVersion === version) { await uninstallMod(game.appid, mod.id); } else { await deleteModVersion(game.appid, mod.id, version); } await onRefresh(); setBusy(false); }}
      />
    );

    if (dependents.length > 0) {
      showModal(
        <DependentsModal
          dependentNames={dependents.map(m => m.name)}
          onDisable={async (close: () => void) => { close(); setBusy(true); for (const dep of dependents) await toggleMod(game.appid, dep.id, false); await onRefresh(); setBusy(false); showDeleteModal(); }}
          onIgnore={async (close: () => void) => { close(); showDeleteModal(); }}
          onDelete={async (close: () => void) => { close(); setBusy(true); for (const dep of dependents) await uninstallMod(game.appid, dep.id); await uninstallMod(game.appid, mod.id); await onRefresh(); setBusy(false); }}
        />
      );
      return;
    }
    showDeleteModal();
  };

  const handleToggleMod = async (id: string, enable: boolean) => {
    if (enable) {
      const mod = game.mods.find(m => m.id === id);
      if (mod) {
        const missingDeps = (mod.dependencies ?? []).filter(depId => !game.installed_mods.find(m => m.id === depId && m.enabled));
        if (missingDeps.length > 0) {
          const missingNames = missingDeps.map(depId => game.mods.find(m => m.id === depId)?.name ?? depId);
          const notInstalled = missingDeps.filter(depId => !game.installed_mods.find(m => m.id === depId));
          const disabled = missingDeps.filter(depId => game.installed_mods.find(m => m.id === depId && !m.enabled));
          showModal(
            <DependencyInstallModal
              modName={mod.name} dependencyNames={missingNames}
              actionLabel={notInstalled.length > 0 ? 'Install & Enable' : 'Enable dependencies'}
              onInstall={async (close: () => void) => {
                close(); setBusy(true); setInstalling(true); setProgress(0);
                for (const depId of notInstalled) {
                  const depMod = game.mods.find(m => m.id === depId);
                  if (depMod) {
                    const ok = await installMod(game.appid, depId, null);
                    if (ok === null) { setInstalling(false); setBusy(false); await onRefresh(); return; }
                    if (!ok) { toaster.toast({ title: 'Moddy', body: `Failed to install ${depMod.name}` }); setInstalling(false); setBusy(false); await onRefresh(); return; }
                  }
                }
                setInstalling(false);
                for (const depId of disabled) await toggleMod(game.appid, depId, true);
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
      const dependents = game.mods.filter(m => (m.dependencies ?? []).includes(id) && game.installed_mods.find(im => im.id === m.id && im.enabled));
      if (dependents.length > 0) {
        showModal(
          <DependentsModal
            dependentNames={dependents.map(m => m.name)}
            onDisable={async (close: () => void) => { close(); setBusy(true); for (const dep of dependents) await toggleMod(game.appid, dep.id, false); await toggleMod(game.appid, id, false); await onRefresh(); setBusy(false); }}
            onIgnore={async (close: () => void) => { close(); setBusy(true); await toggleMod(game.appid, id, false); await onRefresh(); setBusy(false); }}
            onDelete={async (close: () => void) => { close(); setBusy(true); for (const dep of dependents) await uninstallMod(game.appid, dep.id); await toggleMod(game.appid, id, false); await onRefresh(); setBusy(false); }}
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
    if (ok) { setUpdates(updates.filter(u => u.id !== mod.id)); toaster.toast({ title: 'Moddy', body: `${mod.name} updated` }); }
    else { toaster.toast({ title: 'Moddy', body: `Failed to update ${mod.name}` }); }
    await onRefresh(); setBusy(false);
  };

  const handleInstallModVersion = async (mod: ModInfo, version: string) => {
    const wasInstalled = installedIds.has(mod.id);
    setBusy(true); setInstalling(true); setProgress(0);
    const ok = await installMod(game.appid, mod.id, version);
    setInstalling(false);
    if (ok === null) { await onRefresh(); setBusy(false); return; }
    if (!wasInstalled) { toaster.toast({ title: 'Moddy', body: ok ? `${mod.name} installed` : `Failed to install ${mod.name}` }); }
    else if (!ok) { toaster.toast({ title: 'Moddy', body: `Failed to change ${mod.name} to ${version}` }); }
    await onRefresh(); setBusy(false);
  };

  const handleChangeVersion = async (mod: ModInfo) => {
    const releases = await getModReleases(game.appid, mod.id);
    if (releases.length === 0) { toaster.toast({ title: 'Moddy', body: 'Could not fetch releases' }); return; }
    const currentVersion = game.installed_mods.find(m => m.id === mod.id)?.version ?? null;
    const backedUp = await getBackedUpVersions(game.appid, mod.id);
    showModal(
      <VersionPickerModal
        mod={mod} releases={releases} installedVersion={currentVersion} backedUpVersions={backedUp}
        onSelect={(version, close) => { close(); handleInstallModVersion(mod, version); }}
      />
    );
  };

  return (
    <Focusable style={{ display: 'flex', height: '100%', overflow: 'hidden' }}>
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