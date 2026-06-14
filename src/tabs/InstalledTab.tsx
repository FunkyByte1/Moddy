import { showModal, Focusable, ButtonItem, PanelSection, PanelSectionRow } from '@decky/ui';
import { toaster } from '@decky/api';
import { useState, useEffect, FC } from 'react';

import {
  GameStatus, ModInfo, ModUpdate, InstalledMod,
  installMod, installThunderstoreMod, uninstallMod, toggleMod,
  getModReleases, getBackedUpVersions, deleteModVersion, getBrowseDenylist,
} from '../types';
import { ModEntry } from '../components/ModEntry';
import ModDetailPanel from '../components/ModDetailPanel';
import ModListItem from '../components/ModListItem';
import { InstalledFilter, installedMatchesFilter } from '../components/modals/InstalledFilterModal';
import VersionPickerModal from '../components/modals/VersionPickerModal';
import DeleteVersionModal from '../components/modals/DeleteVersionModal';
import DependentsModal from '../components/modals/DependentsModal';
import DependencyInstallModal from '../components/modals/DependencyInstallModal';
import { showOrphanCleanup, RemovalMode } from '../orphanCleanup';

// Thunderstore deps are recorded as versioned full_names ("Owner-Mod-1.2.3");
// the install id drops the trailing version segment.
const stripVersion = (dep: string) => dep.split('-').slice(0, -1).join('-');

const InstalledTab: FC<{
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
  filter: InstalledFilter;
  selectionMode: boolean;
  setSelectionMode: (v: boolean) => void;
}> = ({ game, onRefresh, updates, setUpdates, installing, progress, setInstalling, setProgress, onCancel, onMenuButton, onFilterButton, filter, selectionMode, setSelectionMode }) => {
  const [busy, setBusy] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [bulkStep, setBulkStep] = useState<{ action: 'enable' | 'disable' | 'uninstall'; current: number; total: number; name: string } | null>(null);
  // Modloader/mod-manager packages (e.g. BepInExPack) are provided by the Mod
  // Loader tab, not tracked as plugins — so a mod's dependency on one is always
  // satisfied and must not be flagged missing or installed as a plugin.
  const [denylist, setDenylist] = useState<Set<string>>(new Set());

  useEffect(() => {
    if (!selectionMode) setSelectedIds(new Set());
  }, [selectionMode]);

  useEffect(() => {
    getBrowseDenylist().then(d => setDenylist(new Set(d.map(x => x.toLowerCase())))).catch(() => {});
  }, []);

  const installedLowerSet = new Set(game.installed_mods.map(m => m.id.toLowerCase()));
  const enabledLowerSet = new Set(game.installed_mods.filter(m => m.enabled).map(m => m.id.toLowerCase()));

  // A mod's plugin dependencies: version-stripped, with modloader-provided
  // (denylisted) packages removed.
  const modDeps = (im?: InstalledMod | null): string[] =>
    (im?.meta?.dependencies ?? [])
      .map(stripVersion)
      .filter(d => d && !denylist.has(d.toLowerCase()));

  const metaName = (baseId: string): string =>
    game.installed_mods.find(m => m.id.toLowerCase() === baseId.toLowerCase())?.meta?.name ?? baseId;

  const allEntries: ModEntry[] = game.installed_mods.map(im => {
    const meta = im.meta ?? null;
    const baseDeps = modDeps(im);
    const dependenciesMet = !im.enabled || baseDeps.every(d => enabledLowerSet.has(d.toLowerCase()));
    const name = meta?.name || im.filename.replace(/\.dll$/, '');
    return {
      id: im.id, name,
      installed: true, enabled: im.enabled, version: im.version,
      hasUpdate: !!updates.find(u => u.id === im.id),
      dependenciesMet,
      isLibrary: !!im.is_library,
      info: {
        id: im.id, name, description: meta?.description ?? '', filename: im.filename,
        source: { type: 'unknown', owner: '', repo: '', asset: '' },
        author: meta?.author, thumbnail: meta?.thumbnail, dependencies: baseDeps,
      },
    };
  });

  const modEntries = allEntries.filter(e => installedMatchesFilter(e, filter));
  const selectedEntry = modEntries[Math.min(selectedIndex, modEntries.length - 1)];

  // Installed mods (enabled or not) that declare `id` as a dependency.
  const dependentsOf = (id: string, requireEnabled: boolean): InstalledMod[] => {
    const target = id.toLowerCase();
    return game.installed_mods.filter(m => {
      if (m.id.toLowerCase() === target) return false;
      if (requireEnabled && !m.enabled) return false;
      return (m.meta?.dependencies ?? []).some(d => stripVersion(d).toLowerCase() === target);
    });
  };

  // Curated mods install via install_mod; browsed Thunderstore mods (unknown to
  // game.mods) must go through install_thunderstore_mod.
  const installVersion = (id: string, version: string | null) =>
    game.mods.some(m => m.id === id)
      ? installMod(game.appid, id, version)
      : installThunderstoreMod(game.appid, id, version);

  // After removing/disabling mods, offer to clean up library deps they orphaned.
  const cleanupOrphans = (removedIds: string[], mode: RemovalMode) =>
    showOrphanCleanup({ game, denylist, removedIds, mode, onRefresh, setBusy });

  const handleToggleMod = async (id: string, enable: boolean) => {
    if (enable) {
      const im = game.installed_mods.find(m => m.id === id);
      const baseDeps = modDeps(im);
      const notEnabled = baseDeps.filter(d => !enabledLowerSet.has(d.toLowerCase()));
      if (notEnabled.length > 0) {
        const missingDeps = notEnabled.filter(d => !installedLowerSet.has(d.toLowerCase()));
        const disabledDeps = notEnabled.filter(d => installedLowerSet.has(d.toLowerCase()));
        showModal(
          <DependencyInstallModal
            modName={im?.meta?.name ?? id}
            dependencyNames={notEnabled.map(d => metaName(d))}
            actionLabel={missingDeps.length > 0 ? 'Install & Enable' : 'Enable dependencies'}
            onInstall={async (close: () => void) => {
              close(); setBusy(true); setInstalling(true); setProgress(0);
              for (const dep of missingDeps) {
                const ok = await installThunderstoreMod(game.appid, dep, null);
                if (ok === null) { setInstalling(false); setBusy(false); await onRefresh(); return; }
                if (!ok) { toaster.toast({ title: 'Moddy', body: `Failed to install ${metaName(dep)}` }); setInstalling(false); setBusy(false); await onRefresh(); return; }
              }
              setInstalling(false);
              // Newly installed deps come in enabled; only the already-installed
              // disabled ones need an explicit toggle.
              for (const dep of disabledDeps) {
                const depMod = game.installed_mods.find(m => m.id.toLowerCase() === dep.toLowerCase());
                if (depMod) await toggleMod(game.appid, depMod.id, true);
              }
              await toggleMod(game.appid, id, true);
              await onRefresh(); setBusy(false);
            }}
          />
        );
        return;
      }
    }

    if (!enable) {
      const dependents = dependentsOf(id, true);
      if (dependents.length > 0) {
        showModal(
          <DependentsModal
            dependentNames={dependents.map(m => m.meta?.name ?? m.filename.replace(/\.dll$/, ''))}
            onDisable={async (close: () => void) => { close(); setBusy(true); for (const dep of dependents) await toggleMod(game.appid, dep.id, false); await toggleMod(game.appid, id, false); await onRefresh(); setBusy(false); cleanupOrphans([id, ...dependents.map(d => d.id)], 'disable'); }}
            onIgnore={async (close: () => void) => { close(); setBusy(true); await toggleMod(game.appid, id, false); await onRefresh(); setBusy(false); cleanupOrphans([id], 'disable'); }}
            onDelete={async (close: () => void) => { close(); setBusy(true); for (const dep of dependents) await uninstallMod(game.appid, dep.id); await toggleMod(game.appid, id, false); await onRefresh(); setBusy(false); cleanupOrphans([id, ...dependents.map(d => d.id)], 'disable'); }}
          />
        );
        return;
      }
    }
    setBusy(true);
    await toggleMod(game.appid, id, enable);
    await onRefresh(); setBusy(false);
    if (!enable) cleanupOrphans([id], 'disable');
  };

  const handleDeleteMod = async (mod: ModInfo) => {
    const currentVersion = game.installed_mods.find(m => m.id === mod.id)?.version ?? null;
    const backedUp = await getBackedUpVersions(game.appid, mod.id);
    const dependents = dependentsOf(mod.id, false);

    const showDeleteModal = () => showModal(
      <DeleteVersionModal
        modName={mod.name} currentVersion={currentVersion} backedUpVersions={backedUp}
        onDeleteAll={async (c) => { c(); setBusy(true); await uninstallMod(game.appid, mod.id); await onRefresh(); setBusy(false); cleanupOrphans([mod.id], 'uninstall'); }}
        onDeleteVersion={async (version, c) => { c(); setBusy(true); if (currentVersion === version) { await uninstallMod(game.appid, mod.id); } else { await deleteModVersion(game.appid, mod.id, version); } await onRefresh(); setBusy(false); if (currentVersion === version) cleanupOrphans([mod.id], 'uninstall'); }}
      />
    );

    if (dependents.length > 0) {
      showModal(
        <DependentsModal
          dependentNames={dependents.map(m => m.meta?.name ?? m.filename.replace(/\.dll$/, ''))}
          onDisable={async (close: () => void) => { close(); setBusy(true); for (const dep of dependents) await toggleMod(game.appid, dep.id, false); await onRefresh(); setBusy(false); showDeleteModal(); }}
          onIgnore={async (close: () => void) => { close(); showDeleteModal(); }}
          onDelete={async (close: () => void) => { close(); setBusy(true); for (const dep of dependents) await uninstallMod(game.appid, dep.id); await uninstallMod(game.appid, mod.id); await onRefresh(); setBusy(false); cleanupOrphans([mod.id, ...dependents.map(d => d.id)], 'uninstall'); }}
        />
      );
      return;
    }
    showDeleteModal();
  };

  const handleUpdateMod = async (mod: ModInfo) => {
    const upd = updates.find(u => u.id === mod.id);
    setBusy(true); setInstalling(true); setProgress(0);
    const ok = await installVersion(mod.id, upd?.latest_version ?? null);
    setInstalling(false);
    if (ok === null) { await onRefresh(); setBusy(false); return; }
    if (ok) { setUpdates(updates.filter(u => u.id !== mod.id)); toaster.toast({ title: 'Moddy', body: `${mod.name} updated` }); }
    else { toaster.toast({ title: 'Moddy', body: `Failed to update ${mod.name}` }); }
    await onRefresh(); setBusy(false);
  };

  const handleInstallModVersion = async (mod: ModInfo, version: string) => {
    setBusy(true); setInstalling(true); setProgress(0);
    const ok = await installVersion(mod.id, version);
    setInstalling(false);
    if (ok === null) { await onRefresh(); setBusy(false); return; }
    if (!ok) { toaster.toast({ title: 'Moddy', body: `Failed to change ${mod.name} to ${version}` }); }
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
  const topoEnableOrder = (ids: string[]): string[] => {
    const idSet = new Set(ids.map(i => i.toLowerCase()));
    const visited = new Set<string>();
    const result: string[] = [];
    const visit = (id: string) => {
      const lower = id.toLowerCase();
      if (visited.has(lower)) return;
      visited.add(lower);
      const im = game.installed_mods.find(m => m.id.toLowerCase() === lower);
      for (const dep of modDeps(im)) {
        if (idSet.has(dep.toLowerCase())) {
          const depMod = game.installed_mods.find(m => m.id.toLowerCase() === dep.toLowerCase());
          if (depMod) visit(depMod.id);
        }
      }
      result.push(id);
    };
    for (const id of ids) visit(id);
    return result;
  };

  const bulkEnableTargets = [...selectedIds].filter(id => !enabledLowerSet.has(id.toLowerCase()));
  const bulkDisableTargets = [...selectedIds].filter(id => enabledLowerSet.has(id.toLowerCase()));
  const bulkUninstallTargets = [...selectedIds];

  const bulkStepName = (id: string) =>
    game.installed_mods.find(m => m.id === id)?.meta?.name
    ?? game.installed_mods.find(m => m.id === id)?.filename ?? id;

  const runBulkEnable = async (ids: string[]) => {
    if (ids.length === 0) return;
    const idSetLower = new Set(ids.map(i => i.toLowerCase()));
    // Deps of the selection that aren't already enabled and aren't themselves
    // being enabled — split into already-installed-but-disabled vs not installed.
    const extraDisabled = new Set<string>();
    const extraMissing = new Set<string>();
    for (const id of ids) {
      const im = game.installed_mods.find(m => m.id === id);
      for (const dep of modDeps(im)) {
        const dl = dep.toLowerCase();
        if (enabledLowerSet.has(dl) || idSetLower.has(dl)) continue;
        if (installedLowerSet.has(dl)) extraDisabled.add(dep); else extraMissing.add(dep);
      }
    }

    const execute = async () => {
      setBusy(true);
      if (extraMissing.size > 0) { setInstalling(true); setProgress(0); }
      for (const dep of extraMissing) {
        const ok = await installThunderstoreMod(game.appid, dep, null);
        if (ok === null) { setInstalling(false); setBulkStep(null); setSelectionMode(false); await onRefresh(); setBusy(false); return; }
        if (!ok) { toaster.toast({ title: 'Moddy', body: `Failed to install ${metaName(dep)}` }); setInstalling(false); setBulkStep(null); setSelectionMode(false); await onRefresh(); setBusy(false); return; }
      }
      setInstalling(false);
      for (const dep of extraDisabled) {
        const depMod = game.installed_mods.find(m => m.id.toLowerCase() === dep.toLowerCase());
        if (depMod) await toggleMod(game.appid, depMod.id, true);
      }
      const ordered = topoEnableOrder(ids);
      for (let i = 0; i < ordered.length; i++) {
        setBulkStep({ action: 'enable', current: i + 1, total: ordered.length, name: bulkStepName(ordered[i]) });
        await toggleMod(game.appid, ordered[i], true);
      }
      setBulkStep(null);
      toaster.toast({ title: 'Moddy', body: `Enabled ${ordered.length} mod${ordered.length === 1 ? '' : 's'}` });
      setSelectionMode(false);
      await onRefresh(); setBusy(false);
    };

    if (extraDisabled.size + extraMissing.size > 0) {
      const names = [...extraMissing, ...extraDisabled].map(d => metaName(d));
      showModal(
        <DependencyInstallModal
          modName={`${ids.length} selected mod${ids.length === 1 ? '' : 's'}`}
          dependencyNames={names}
          actionLabel={extraMissing.size > 0 ? 'Install & Enable' : 'Enable dependencies'}
          onInstall={(close) => { close(); execute(); }}
        />
      );
    } else {
      execute();
    }
  };

  const runBulkDisable = async (ids: string[]) => {
    if (ids.length === 0) return;
    const targetSet = new Set(ids.map(i => i.toLowerCase()));
    // Enabled mods outside the selection that depend on something being disabled.
    const dependents = game.installed_mods.filter(m =>
      m.enabled &&
      !targetSet.has(m.id.toLowerCase()) &&
      (m.meta?.dependencies ?? []).some(d => targetSet.has(stripVersion(d).toLowerCase()))
    );

    const disableTargets = async () => {
      const ordered = topoEnableOrder(ids).reverse();
      for (let i = 0; i < ordered.length; i++) {
        setBulkStep({ action: 'disable', current: i + 1, total: ordered.length, name: bulkStepName(ordered[i]) });
        await toggleMod(game.appid, ordered[i], false);
      }
      setBulkStep(null);
      toaster.toast({ title: 'Moddy', body: `Disabled ${ordered.length} mod${ordered.length === 1 ? '' : 's'}` });
    };

    if (dependents.length > 0) {
      showModal(
        <DependentsModal
          dependentNames={dependents.map(m => m.meta?.name ?? m.filename.replace(/\.dll$/, ''))}
          onDisable={async (close) => { close(); setBusy(true); for (const dep of dependents) await toggleMod(game.appid, dep.id, false); await disableTargets(); setSelectionMode(false); await onRefresh(); setBusy(false); cleanupOrphans([...ids, ...dependents.map(d => d.id)], 'disable'); }}
          onIgnore={async (close) => { close(); setBusy(true); await disableTargets(); setSelectionMode(false); await onRefresh(); setBusy(false); cleanupOrphans(ids, 'disable'); }}
          onDelete={async (close) => { close(); setBusy(true); for (const dep of dependents) await uninstallMod(game.appid, dep.id); await disableTargets(); setSelectionMode(false); await onRefresh(); setBusy(false); cleanupOrphans([...ids, ...dependents.map(d => d.id)], 'disable'); }}
        />
      );
    } else {
      setBusy(true);
      await disableTargets();
      setSelectionMode(false);
      await onRefresh(); setBusy(false);
      cleanupOrphans(ids, 'disable');
    }
  };

  const handleBulkUninstall = async () => {
    if (bulkUninstallTargets.length === 0) return;
    const targetSet = new Set(bulkUninstallTargets.map(i => i.toLowerCase()));
    const dependents = game.installed_mods.filter(m =>
      !targetSet.has(m.id.toLowerCase()) &&
      (m.meta?.dependencies ?? []).some(d => targetSet.has(stripVersion(d).toLowerCase()))
    );

    const uninstallAll = async () => {
      let failed = 0;
      for (let i = 0; i < bulkUninstallTargets.length; i++) {
        const id = bulkUninstallTargets[i];
        const name = game.installed_mods.find(m => m.id === id)?.meta?.name
          ?? game.installed_mods.find(m => m.id === id)?.filename ?? id;
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
          dependentNames={dependents.map(m => m.meta?.name ?? m.filename.replace(/\.dll$/, ''))}
          onDisable={async (close) => { close(); setBusy(true); for (const dep of dependents) await toggleMod(game.appid, dep.id, false); await uninstallAll(); setSelectionMode(false); await onRefresh(); setBusy(false); cleanupOrphans(bulkUninstallTargets, 'uninstall'); }}
          onIgnore={async (close) => { close(); setBusy(true); await uninstallAll(); setSelectionMode(false); await onRefresh(); setBusy(false); cleanupOrphans(bulkUninstallTargets, 'uninstall'); }}
          onDelete={async (close) => { close(); setBusy(true); for (const dep of dependents) await uninstallMod(game.appid, dep.id); await uninstallAll(); setSelectionMode(false); await onRefresh(); setBusy(false); cleanupOrphans([...bulkUninstallTargets, ...dependents.map(d => d.id)], 'uninstall'); }}
        />
      );
    } else {
      setBusy(true);
      await uninstallAll();
      setSelectionMode(false);
      await onRefresh(); setBusy(false);
      cleanupOrphans(bulkUninstallTargets, 'uninstall');
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
            {allEntries.length === 0 ? 'No mods installed' : 'No mods match the current filter'}
          </div>
        ) : modEntries.map((entry, i) => (
          <ModListItem key={entry.id} entry={entry} selected={i === selectedIndex}
            selectionMode={selectionMode} isChecked={selectedIds.has(entry.id)}
            showThumbnail onToggle={handleToggleMod} onSelectToggle={toggleSelected}
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
                {bulkStep.action === 'enable' ? 'Enabling' : bulkStep.action === 'disable' ? 'Disabling' : 'Uninstalling'} {bulkStep.current} of {bulkStep.total}
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
              <ButtonItem layout="below" disabled={busy || bulkEnableTargets.length === 0} onClick={() => runBulkEnable(bulkEnableTargets)}>
                {`Enable Selected${bulkEnableTargets.length > 0 ? ` (${bulkEnableTargets.length})` : ''}`}
              </ButtonItem>
            </PanelSectionRow>
            <PanelSectionRow>
              <ButtonItem layout="below" disabled={busy || bulkDisableTargets.length === 0} onClick={() => runBulkDisable(bulkDisableTargets)}>
                {`Disable Selected${bulkDisableTargets.length > 0 ? ` (${bulkDisableTargets.length})` : ''}`}
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
          updates={updates} onInstall={() => {}} onDelete={handleDeleteMod}
          onUpdate={handleUpdateMod} onChangeVersion={handleChangeVersion}
          onCancel={onCancel} onMenuButton={onMenuButton} onFilterButton={onFilterButton}
        />
      )}
    </Focusable>
  );
};

export default InstalledTab;
