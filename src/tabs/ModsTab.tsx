import { showModal, Focusable, ButtonItem, PanelSection, PanelSectionRow } from '@decky/ui';
import { toaster } from '@decky/api';
import { useState, useEffect, FC } from 'react';

import {
  GameStatus, ModInfo, ModUpdate,
  installMod, uninstallMod, toggleMod,
  getModReleases, getBackedUpVersions, deleteModVersion,
} from '../types';
import { ModEntry } from '../components/ModEntry';
import ModDetailPanel from '../components/ModDetailPanel';
import ModListItem from '../components/ModListItem';
import { ModFilter, modMatchesFilter } from '../components/modals/FilterModal';
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
  onFilterButton: () => void;
  filter: ModFilter;
  selectionMode: boolean;
  setSelectionMode: (v: boolean) => void;
}> = ({ game, onRefresh, updates, setUpdates, installing, progress, setInstalling, setProgress, onCancel, onMenuButton, onFilterButton, filter, selectionMode, setSelectionMode }) => {
  const [busy, setBusy] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [bulkStep, setBulkStep] = useState<{ action: 'install' | 'uninstall'; current: number; total: number; name: string } | null>(null);

  useEffect(() => {
    if (!selectionMode) setSelectedIds(new Set());
  }, [selectionMode]);

  const installedIds = new Set(game.installed_mods.map(m => m.id));

  const allEntries: ModEntry[] = game.mods.map(mod => {
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
    if (!allEntries.find(e => e.id === installed.id)) {
      allEntries.push({
        id: installed.id, name: installed.filename.replace('.dll', ''),
        installed: true, enabled: installed.enabled, version: installed.version,
        hasUpdate: false, dependenciesMet: true,
        info: { id: installed.id, name: installed.filename.replace('.dll', ''), description: '', filename: installed.filename, source: { type: 'unknown', owner: '', repo: '', asset: '' } },
      });
    }
  });

  const modEntries = allEntries.filter(e => modMatchesFilter(e, filter));
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

  const toggleSelected = (id: string) => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const allFilteredSelected = modEntries.length > 0 && modEntries.every(e => selectedIds.has(e.id));
  const toggleSelectAll = () => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (allFilteredSelected) {
        for (const e of modEntries) next.delete(e.id);
      } else {
        for (const e of modEntries) next.add(e.id);
      }
      return next;
    });
  };

  // Order ids so each mod's selected-group dependencies come before it.
  const topoInstallOrder = (ids: string[]): string[] => {
    const idSet = new Set(ids);
    const visited = new Set<string>();
    const result: string[] = [];
    const visit = (id: string) => {
      if (visited.has(id)) return;
      visited.add(id);
      const mod = game.mods.find(m => m.id === id);
      for (const dep of mod?.dependencies ?? []) {
        if (idSet.has(dep)) visit(dep);
      }
      result.push(id);
    };
    for (const id of ids) visit(id);
    return result;
  };

  const bulkInstallTargets = [...selectedIds].filter(id => !installedIds.has(id));
  const bulkUninstallTargets = [...selectedIds].filter(id => installedIds.has(id));

  const handleBulkInstall = async () => {
    if (bulkInstallTargets.length === 0) return;
    const targetSet = new Set(bulkInstallTargets);
    const extraDeps = new Set<string>();
    for (const id of bulkInstallTargets) {
      const mod = game.mods.find(m => m.id === id);
      for (const dep of mod?.dependencies ?? []) {
        if (!installedIds.has(dep) && !targetSet.has(dep)) extraDeps.add(dep);
      }
    }

    const runInstall = async () => {
      setBusy(true); setInstalling(true); setProgress(0);
      const ordered = topoInstallOrder([...extraDeps, ...bulkInstallTargets]);
      for (let i = 0; i < ordered.length; i++) {
        const id = ordered[i];
        const name = game.mods.find(m => m.id === id)?.name ?? id;
        setBulkStep({ action: 'install', current: i + 1, total: ordered.length, name });
        const ok = await installMod(game.appid, id, null);
        if (ok === null) { setBulkStep(null); setInstalling(false); setSelectionMode(false); await onRefresh(); setBusy(false); return; }
        if (!ok) {
          toaster.toast({ title: 'Moddy', body: `Failed to install ${name}` });
          setBulkStep(null); setInstalling(false); setSelectionMode(false); await onRefresh(); setBusy(false); return;
        }
        setProgress(0);
      }
      setBulkStep(null);
      setInstalling(false);
      toaster.toast({ title: 'Moddy', body: `Installed ${bulkInstallTargets.length} mod${bulkInstallTargets.length === 1 ? '' : 's'}` });
      setSelectionMode(false);
      await onRefresh(); setBusy(false);
    };

    if (extraDeps.size > 0) {
      const depNames = [...extraDeps].map(id => game.mods.find(m => m.id === id)?.name ?? id);
      const label = `${bulkInstallTargets.length} selected mod${bulkInstallTargets.length === 1 ? '' : 's'}`;
      showModal(
        <DependencyInstallModal
          modName={label}
          dependencyNames={depNames}
          onInstall={(close) => { close(); runInstall(); }}
        />
      );
    } else {
      runInstall();
    }
  };

  const handleBulkUninstall = async () => {
    if (bulkUninstallTargets.length === 0) return;
    const targetSet = new Set(bulkUninstallTargets);
    const dependents = game.mods.filter(m =>
      installedIds.has(m.id) &&
      !targetSet.has(m.id) &&
      (m.dependencies ?? []).some(d => targetSet.has(d))
    );

    const uninstallAll = async () => {
      let failed = 0;
      for (let i = 0; i < bulkUninstallTargets.length; i++) {
        const id = bulkUninstallTargets[i];
        const name = game.mods.find(m => m.id === id)?.name
          ?? game.installed_mods.find(m => m.id === id)?.filename
          ?? id;
        setBulkStep({ action: 'uninstall', current: i + 1, total: bulkUninstallTargets.length, name });
        const ok = await uninstallMod(game.appid, id);
        if (!ok) failed++;
      }
      setBulkStep(null);
      const ok = bulkUninstallTargets.length - failed;
      toaster.toast({
        title: 'Moddy',
        body: `Uninstalled ${ok} mod${ok === 1 ? '' : 's'}${failed > 0 ? ` (${failed} failed)` : ''}`,
      });
    };

    if (dependents.length > 0) {
      showModal(
        <DependentsModal
          dependentNames={dependents.map(m => m.name)}
          onDisable={async (close) => {
            close(); setBusy(true);
            for (const dep of dependents) await toggleMod(game.appid, dep.id, false);
            await uninstallAll();
            setSelectionMode(false);
            await onRefresh(); setBusy(false);
          }}
          onIgnore={async (close) => {
            close(); setBusy(true);
            await uninstallAll();
            setSelectionMode(false);
            await onRefresh(); setBusy(false);
          }}
          onDelete={async (close) => {
            close(); setBusy(true);
            for (const dep of dependents) await uninstallMod(game.appid, dep.id);
            await uninstallAll();
            setSelectionMode(false);
            await onRefresh(); setBusy(false);
          }}
        />
      );
    } else {
      setBusy(true);
      await uninstallAll();
      setSelectionMode(false);
      await onRefresh(); setBusy(false);
    }
  };

  return (
    <Focusable style={{ display: 'flex', height: '100%', overflow: 'hidden' }}>
      <Focusable
        style={{ width: '30%', overflowY: 'auto', paddingBottom: '60px', borderRight: '1px solid var(--gpColorSeparator)', padding: '8px' }}
        onMenuButton={onMenuButton}
        onMenuActionDescription="Options"
        onSecondaryButton={onFilterButton}
        onSecondaryActionDescription="Filter"
      >
        {modEntries.length === 0 ? (
          <div style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.85em', padding: '8px' }}>
            {allEntries.length === 0 ? 'No mods available' : 'No mods match the current filter'}
          </div>
        ) : modEntries.map((entry, i) => (
          <ModListItem key={entry.id} entry={entry} selected={i === selectedIndex}
            selectionMode={selectionMode} isChecked={selectedIds.has(entry.id)}
            onToggle={handleToggleMod} onSelectToggle={toggleSelected}
            onFocus={() => setSelectedIndex(i)} />
        ))}
      </Focusable>

      {selectionMode ? (
        <Focusable
          style={{ flex: 1, overflowY: 'auto', padding: '12px 16px', paddingBottom: '60px', display: 'flex', flexDirection: 'column' }}
          onMenuButton={onMenuButton}
          onMenuActionDescription="Options"
          onSecondaryButton={onFilterButton}
          onSecondaryActionDescription="Filter"
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
          <div style={{ fontWeight: 'bold', fontSize: '1.1em', marginBottom: '8px' }}>
            Bulk Selection
          </div>
          <div style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.9em', marginBottom: '12px' }}>
            {selectedIds.size === 0
              ? 'Press A on a mod in the list to add it to the selection.'
              : `${selectedIds.size} mod${selectedIds.size === 1 ? '' : 's'} selected`}
          </div>
          {bulkStep && (
            <div style={{
              padding: '8px 10px', marginBottom: '12px', borderRadius: '4px',
              background: 'var(--gpColorBgTertiary)', fontSize: '0.85em',
            }}>
              <div style={{ fontWeight: 'bold', marginBottom: '2px' }}>
                {bulkStep.action === 'install' ? 'Installing' : 'Uninstalling'} {bulkStep.current} of {bulkStep.total}
              </div>
              <div style={{ color: 'var(--gpColorTextSecondary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {bulkStep.name}
              </div>
            </div>
          )}
          <PanelSection>
            <PanelSectionRow>
              <ButtonItem layout="below" disabled={busy || modEntries.length === 0} onClick={toggleSelectAll}>
                {allFilteredSelected ? 'Deselect All' : 'Select All'}
              </ButtonItem>
            </PanelSectionRow>
            <PanelSectionRow>
              <ButtonItem layout="below" disabled={busy || bulkInstallTargets.length === 0} onClick={handleBulkInstall}>
                {`Install Selected${bulkInstallTargets.length > 0 ? ` (${bulkInstallTargets.length})` : ''}`}
              </ButtonItem>
            </PanelSectionRow>
            <PanelSectionRow>
              <ButtonItem layout="below" disabled={busy || bulkUninstallTargets.length === 0} onClick={handleBulkUninstall}>
                {`Uninstall Selected${bulkUninstallTargets.length > 0 ? ` (${bulkUninstallTargets.length})` : ''}`}
              </ButtonItem>
            </PanelSectionRow>
            <PanelSectionRow>
              <ButtonItem layout="below" disabled={busy} onClick={() => setSelectionMode(false)}>
                Cancel Selection
              </ButtonItem>
            </PanelSectionRow>
          </PanelSection>
        </Focusable>
      ) : selectedEntry && (
        <ModDetailPanel
          entry={selectedEntry} game={game} busy={busy} installing={installing} progress={progress}
          updates={updates} onInstall={handleInstallMod} onDelete={handleDeleteMod}
          onUpdate={handleUpdateMod} onChangeVersion={handleChangeVersion}
          onCancel={onCancel} onMenuButton={onMenuButton} onFilterButton={onFilterButton}
        />
      )}
    </Focusable>
  );
};

export default ModsTab;