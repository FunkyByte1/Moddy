import { showModal, ConfirmModal, Focusable, ButtonItem, PanelSection, PanelSectionRow } from '@decky/ui';
import { toaster } from '@decky/api';
import { useState, useEffect, useMemo, useCallback, useRef, FC } from 'react';

import {
  GameStatus, ModInfo, ModUpdate,
  installMod, installThunderstoreMod, uninstallMod, toggleMod,
  getModReleases, getBackedUpVersions, deleteModVersion, getBrowseDenylist,
} from '../types';
import { useQueueFooterProps } from '../components/DownloadQueueModal';
import { ModEntry } from '../components/ModEntry';
import ModDetailPanel from '../components/ModDetailPanel';
import ModListItem from '../components/ModListItem';
import { InstalledFilter, installedMatchesFilter, sortInstalledEntries } from '../components/modals/InstalledFilterModal';
import VersionPickerModal from '../components/modals/VersionPickerModal';
import DeleteVersionModal from '../components/modals/DeleteVersionModal';
import DependentsModal from '../components/modals/DependentsModal';
import DependencyInstallModal from '../components/modals/DependencyInstallModal';
import { findUnusedLibraries, showUnusedLibrariesCleanup } from '../orphanCleanup';
import { modDisplayName } from '../modName';
import { buildModGraph } from '../modGraph';
import { SHOW_VERSION_OPTIONS } from '../featureFlags';

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

  // The installed mods viewed as a dependency graph: lookup indexes plus the transitive
  // enable-deps / dependents / topo-order queries (see src/modGraph.ts), rebuilt only when the
  // installed list or denylist changes so frequent focus/selection renders don't re-scan. The
  // pieces are destructured into the names the handlers below use.
  const graph = useMemo(
    () => buildModGraph(game.installed_mods, denylist),
    [game.installed_mods, denylist],
  );
  const {
    byId: modByLowerId, enabledIds: enabledLowerSet,
    modDeps, collectEnableDeps, collectDependents, topoEnableOrder,
  } = graph;
  const updatesById = useMemo(() => new Map(updates.map(u => [u.id, u])), [updates]);

  const metaName = useCallback((baseId: string): string =>
    modByLowerId.get(baseId.toLowerCase())?.meta?.name ?? baseId,
    [modByLowerId]);

  const allEntries: ModEntry[] = useMemo(() => game.installed_mods.map(im => {
    const meta = im.meta ?? null;
    const baseDeps = modDeps(im);
    const dependenciesMet = !im.enabled || baseDeps.every(d => enabledLowerSet.has(d.toLowerCase()));
    const name = modDisplayName(im);
    return {
      id: im.id, name,
      installed: true, enabled: im.enabled, version: im.version,
      hasUpdate: updatesById.has(im.id),
      dependenciesMet,
      isLibrary: !!im.is_library,
      addedAt: im.added_at ?? 0,
      info: {
        id: im.id, name, description: meta?.description ?? '', filename: im.filename,
        source: { type: 'unknown', owner: '', repo: '', asset: '' },
        author: meta?.author, thumbnail: meta?.thumbnail, dependencies: baseDeps,
      },
    };
  }), [game.installed_mods, modDeps, enabledLowerSet, updatesById]);

  const modEntries = useMemo(
    () => sortInstalledEntries(allEntries.filter(e => installedMatchesFilter(e, filter)), filter.sortBy),
    [allEntries, filter],
  );
  const selectedEntry = modEntries[Math.min(selectedIndex, modEntries.length - 1)];


  // Version changes / updates re-download through the Thunderstore install path
  // (the only catalog with versioned releases surfaced here).
  const installVersion = (id: string, version: string | null) =>
    installThunderstoreMod(game.appid, id, version);

  // Install a missing dependency through the right backend: Workshop deps subscribe via
  // installMod (synthetic ids), Thunderstore deps download via installThunderstoreMod.
  const installDep = (id: string) =>
    /^workshop\.\d+\.\d+$/.test(id)
      ? installMod(game.appid, id, null)
      : installThunderstoreMod(game.appid, id, null);

  // Library mods nothing installed relies on anymore. Surfaced as an on-demand cleanup chip rather
  // than auto-prompted after every removal — removing a mod no longer interrupts with an orphan modal.
  const unusedLibraries = useMemo(() => findUnusedLibraries(game, denylist), [game, denylist]);
  const showLibraryCleanup = () => showUnusedLibrariesCleanup({ game, denylist, onRefresh, setBusy });

  const handleToggleMod = async (id: string, enable: boolean) => {
    if (enable) {
      const im = modByLowerId.get(id.toLowerCase());
      const { missing: missingDeps, disabled: disabledDeps } = collectEnableDeps([id]);
      if (missingDeps.length + disabledDeps.length > 0) {
        showModal(
          <DependencyInstallModal
            modName={im?.meta?.name ?? id}
            dependencyNames={[...missingDeps, ...disabledDeps].map(d => metaName(d))}
            actionLabel={missingDeps.length > 0 ? 'Install & Enable' : 'Enable dependencies'}
            onInstall={async (close: () => void) => {
              close(); setBusy(true); setInstalling(true); setProgress(0);
              for (const dep of missingDeps) {
                const ok = await installDep(dep);
                if (ok === null) { setInstalling(false); setBusy(false); await onRefresh(); return; }
                if (!ok) { toaster.toast({ title: 'Moddy', body: `Failed to install ${metaName(dep)}` }); setInstalling(false); setBusy(false); await onRefresh(); return; }
              }
              setInstalling(false);
              // Newly installed deps come in enabled; only the already-installed
              // disabled ones need an explicit toggle.
              for (const dep of disabledDeps) {
                const depMod = modByLowerId.get(dep.toLowerCase());
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
      const dependents = collectDependents([id], true);
      if (dependents.length > 0) {
        showModal(
          <DependentsModal
            dependentNames={dependents.map(m => modDisplayName(m))}
            primaryAction="disable"
            onDisable={async (close: () => void) => { close(); setBusy(true); for (const dep of dependents) await toggleMod(game.appid, dep.id, false); await toggleMod(game.appid, id, false); await onRefresh(); setBusy(false); }}
            onKeep={async (close: () => void) => { close(); setBusy(true); await toggleMod(game.appid, id, false); await onRefresh(); setBusy(false); }}
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

  const handleDeleteMod = async (mod: ModInfo) => {
    const currentVersion = modByLowerId.get(mod.id.toLowerCase())?.version ?? null;
    // Backed-up versions only feed the version picker, which is hidden unless SHOW_VERSION_OPTIONS.
    const backedUp = SHOW_VERSION_OPTIONS ? await getBackedUpVersions(game.appid, mod.id) : [];
    const dependents = collectDependents([mod.id], false);

    const showDeleteModal = () => {
      // With version options hidden there's nothing to choose, so the DeleteVersionModal picker
      // degenerates into a single "Delete" button that only opens this same confirmation — a
      // redundant extra step left over from the version-picker era. Go straight to the confirm.
      if (!SHOW_VERSION_OPTIONS) {
        showModal(
          <ConfirmModal
            strTitle={`Delete ${mod.name}?`}
            strDescription="This will remove the mod from disk."
            strOKButtonText="Delete"
            strCancelButtonText="Cancel"
            bDestructiveWarning
            onOK={async () => { setBusy(true); await uninstallMod(game.appid, mod.id); await onRefresh(); setBusy(false); }}
          />
        );
        return;
      }
      showModal(
        <DeleteVersionModal
          modName={mod.name} currentVersion={currentVersion} backedUpVersions={backedUp}
          onDeleteAll={async (c) => { c(); setBusy(true); await uninstallMod(game.appid, mod.id); await onRefresh(); setBusy(false); }}
          onDeleteVersion={async (version, c) => { c(); setBusy(true); if (currentVersion === version) { await uninstallMod(game.appid, mod.id); } else { await deleteModVersion(game.appid, mod.id, version); } await onRefresh(); setBusy(false); }}
        />
      );
    };

    if (dependents.length > 0) {
      showModal(
        <DependentsModal
          dependentNames={dependents.map(m => modDisplayName(m))}
          primaryAction="delete"
          onDisable={async (close: () => void) => { close(); setBusy(true); for (const dep of dependents) await toggleMod(game.appid, dep.id, false); await onRefresh(); setBusy(false); showDeleteModal(); }}
          onKeep={async (close: () => void) => { close(); showDeleteModal(); }}
          onDelete={async (close: () => void) => { close(); setBusy(true); for (const dep of dependents) await uninstallMod(game.appid, dep.id); await uninstallMod(game.appid, mod.id); await onRefresh(); setBusy(false); }}
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
    const currentVersion = modByLowerId.get(mod.id.toLowerCase())?.version ?? null;
    const backedUp = await getBackedUpVersions(game.appid, mod.id);
    showModal(
      <VersionPickerModal
        mod={mod} releases={releases} installedVersion={currentVersion} backedUpVersions={backedUp}
        onSelect={(version, close) => { close(); handleInstallModVersion(mod, version); }}
      />
    );
  };

  const toggleSelected = useCallback((id: string) => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }, []);

  const allFilteredSelected = useMemo(
    () => modEntries.length > 0 && modEntries.every(e => selectedIds.has(e.id)),
    [modEntries, selectedIds],
  );
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


  const bulkEnableTargets = useMemo(
    () => [...selectedIds].filter(id => !enabledLowerSet.has(id.toLowerCase())),
    [selectedIds, enabledLowerSet],
  );
  const bulkDisableTargets = useMemo(
    () => [...selectedIds].filter(id => enabledLowerSet.has(id.toLowerCase())),
    [selectedIds, enabledLowerSet],
  );
  const bulkUninstallTargets = useMemo(() => [...selectedIds], [selectedIds]);

  const bulkStepName = (id: string) =>
    modDisplayName(modByLowerId.get(id.toLowerCase()), id);

  const runBulkEnable = async (ids: string[]) => {
    if (ids.length === 0) return;
    const idSetLower = new Set(ids.map(i => i.toLowerCase()));
    // Transitive deps of the selection, split into already-installed-but-disabled vs
    // not installed. Deps that are themselves in the selection get enabled by the topo
    // loop below, so they're excluded here.
    const { missing, disabled } = collectEnableDeps(ids);
    const extraMissing = new Set(missing.filter(d => !idSetLower.has(d.toLowerCase())));
    const extraDisabled = new Set(disabled.filter(d => !idSetLower.has(d.toLowerCase())));

    const execute = async () => {
      setBusy(true);
      if (extraMissing.size > 0) { setInstalling(true); setProgress(0); }
      for (const dep of extraMissing) {
        const ok = await installDep(dep);
        if (ok === null) { setInstalling(false); setBulkStep(null); setSelectionMode(false); await onRefresh(); setBusy(false); return; }
        if (!ok) { toaster.toast({ title: 'Moddy', body: `Failed to install ${metaName(dep)}` }); setInstalling(false); setBulkStep(null); setSelectionMode(false); await onRefresh(); setBusy(false); return; }
      }
      setInstalling(false);
      for (const dep of extraDisabled) {
        const depMod = modByLowerId.get(dep.toLowerCase());
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
    // Enabled mods outside the selection that (transitively) depend on something being
    // disabled. collectDependents excludes the selection (the roots) itself.
    const dependents = collectDependents(ids, true);

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
          dependentNames={dependents.map(m => modDisplayName(m))}
          primaryAction="disable"
          onDisable={async (close) => { close(); setBusy(true); for (const dep of dependents) await toggleMod(game.appid, dep.id, false); await disableTargets(); setSelectionMode(false); await onRefresh(); setBusy(false); }}
          onKeep={async (close) => { close(); setBusy(true); await disableTargets(); setSelectionMode(false); await onRefresh(); setBusy(false); }}
          onDelete={async (close) => { close(); setBusy(true); for (const dep of dependents) await uninstallMod(game.appid, dep.id); await disableTargets(); setSelectionMode(false); await onRefresh(); setBusy(false); }}
        />
      );
    } else {
      setBusy(true);
      await disableTargets();
      setSelectionMode(false);
      await onRefresh(); setBusy(false);
    }
  };

  const handleBulkUninstall = async () => {
    if (bulkUninstallTargets.length === 0) return;
    // Every installed mod outside the selection that (transitively) depends on one being
    // uninstalled — enabled or not, since uninstall breaks them either way.
    const dependents = collectDependents(bulkUninstallTargets, false);

    const uninstallAll = async () => {
      let failed = 0;
      for (let i = 0; i < bulkUninstallTargets.length; i++) {
        const id = bulkUninstallTargets[i];
        const name = modDisplayName(modByLowerId.get(id.toLowerCase()), id);
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
          dependentNames={dependents.map(m => modDisplayName(m))}
          primaryAction="delete"
          onDisable={async (close) => { close(); setBusy(true); for (const dep of dependents) await toggleMod(game.appid, dep.id, false); await uninstallAll(); setSelectionMode(false); await onRefresh(); setBusy(false); }}
          onKeep={async (close) => { close(); setBusy(true); await uninstallAll(); setSelectionMode(false); await onRefresh(); setBusy(false); }}
          onDelete={async (close) => { close(); setBusy(true); for (const dep of dependents) await uninstallMod(game.appid, dep.id); await uninstallAll(); setSelectionMode(false); await onRefresh(); setBusy(false); }}
        />
      );
    } else {
      setBusy(true);
      await uninstallAll();
      setSelectionMode(false);
      await onRefresh(); setBusy(false);
    }
  };

  // Stable identities so memo(ModListItem) skips rows whose props didn't change on a
  // focus move. A ref keeps the toggle handler current without enumerating its many deps
  // — a wrong useCallback dep list here could act on stale enabled/dependency state.
  const handleToggleRef = useRef(handleToggleMod);
  handleToggleRef.current = handleToggleMod;
  const onItemToggle = useCallback((id: string, enable: boolean) => handleToggleRef.current(id, enable), []);
  const onItemFocus = useCallback((index: number) => setSelectedIndex(index), []);

  const queueFooter = useQueueFooterProps(game.appid);

  return (
    <Focusable style={{ display: 'flex', height: '100%', overflow: 'hidden' }}>
      <Focusable
        style={{ width: '30%', overflowY: 'auto', paddingBottom: '60px', borderRight: '1px solid var(--gpColorSeparator)', padding: '8px' }}
        {...queueFooter}
        onMenuButton={onMenuButton}
        onMenuActionDescription="Options"
        onSecondaryButton={onFilterButton}
        onSecondaryActionDescription="Filter"
      >
        {unusedLibraries.length > 0 && (
          <div style={{ marginBottom: '4px' }}>
            <ButtonItem layout="below" disabled={busy} onClick={showLibraryCleanup}>
              {`🧹 ${unusedLibraries.length} unused librar${unusedLibraries.length === 1 ? 'y' : 'ies'}`}
            </ButtonItem>
          </div>
        )}
        {modEntries.length === 0 ? (
          <div style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.85em', padding: '8px' }}>
            {allEntries.length === 0 ? 'No mods installed' : 'No mods match the current filter'}
          </div>
        ) : modEntries.map((entry, i) => (
          <ModListItem key={entry.id} index={i} entry={entry} selected={i === selectedIndex}
            selectionMode={selectionMode} isChecked={selectedIds.has(entry.id)}
            showThumbnail onToggle={onItemToggle} onSelectToggle={toggleSelected}
            onFocus={onItemFocus} />
        ))}
      </Focusable>

      {selectionMode ? (
        <Focusable
          style={{ flex: 1, overflowY: 'auto', padding: '12px 16px', paddingBottom: '60px', display: 'flex', flexDirection: 'column' }}
          {...queueFooter}
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
          denylist={denylist}
        />
      )}
    </Focusable>
  );
};

export default InstalledTab;
