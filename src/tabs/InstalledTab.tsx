import { showModal, Focusable, ButtonItem, PanelSection, PanelSectionRow } from '@decky/ui';
import { toaster } from '@decky/api';
import { useState, useEffect, useMemo, useCallback, useRef, FC } from 'react';

import {
  GameStatus, ModInfo, ModUpdate, InstalledMod,
  installMod, installThunderstoreMod, uninstallMod, toggleMod,
  getModReleases, getBackedUpVersions, deleteModVersion, getBrowseDenylist,
} from '../types';
import { useQueueFooterProps } from '../components/DownloadQueueModal';
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

  // Lookup structures rebuilt only when the installed-mods list changes, so renders
  // driven by focus/selection state (frequent, especially with large lists) don't
  // re-scan the array. modByLowerId replaces the repeated O(n) `.find()` lookups
  // scattered through the handlers below.
  const modByLowerId = useMemo(
    () => new Map(game.installed_mods.map(m => [m.id.toLowerCase(), m])),
    [game.installed_mods],
  );
  const installedLowerSet = useMemo(
    () => new Set(game.installed_mods.map(m => m.id.toLowerCase())),
    [game.installed_mods],
  );
  const enabledLowerSet = useMemo(
    () => new Set(game.installed_mods.filter(m => m.enabled).map(m => m.id.toLowerCase())),
    [game.installed_mods],
  );
  const updatesById = useMemo(() => new Map(updates.map(u => [u.id, u])), [updates]);

  // Resolve a recorded dependency string to the (lowercase) mod id it refers to. A dep may
  // already be a full Moddy id (a Workshop "workshop.<appid>.<fileid>" id) or a versioned
  // Thunderstore full_name ("Owner-Mod-1.2.3"). Match an installed id directly first, then
  // fall back to version-stripping — blindly stripping mangles hyphen-free ids (e.g. a
  // Workshop id has no '-', so stripping would yield "").
  const resolveDepId = useCallback((rawDep: string): string => {
    const raw = rawDep.toLowerCase();
    if (installedLowerSet.has(raw)) return raw;
    const stripped = stripVersion(rawDep).toLowerCase();
    return stripped || raw;
  }, [installedLowerSet]);

  // A mod's plugin dependencies as resolved (lowercase) mod ids, with modloader-provided
  // (denylisted) packages removed.
  const modDeps = useCallback((im?: InstalledMod | null): string[] =>
    (im?.meta?.dependencies ?? [])
      .map(resolveDepId)
      .filter(d => !denylist.has(d)),
    [resolveDepId, denylist]);

  const metaName = useCallback((baseId: string): string =>
    modByLowerId.get(baseId.toLowerCase())?.meta?.name ?? baseId,
    [modByLowerId]);

  // The transitive set of dependencies that need action before `rootIds` can be enabled.
  // Walks the dependency graph (cycle-guarded) over installed mods, splitting deps into
  // `missing` (not installed → install) and `disabled` (installed but off → enable).
  // Direct-only collection missed deps-of-deps — e.g. A→B→C left C disabled. A missing
  // dep's own sub-deps aren't visible here (it's not in installed_mods); the backend
  // resolves those when it's installed.
  const collectEnableDeps = (rootIds: string[]): { missing: string[]; disabled: string[] } => {
    const missing: string[] = [];
    const disabled: string[] = [];
    const seen = new Set<string>();
    const stack = rootIds.map(i => i.toLowerCase());
    while (stack.length > 0) {
      const cur = stack.pop()!;
      for (const dep of modDeps(modByLowerId.get(cur))) {
        const dl = dep.toLowerCase();
        if (seen.has(dl)) continue;
        seen.add(dl);
        if (enabledLowerSet.has(dl)) {
          stack.push(dl);          // already enabled, but a sub-dep might be off
        } else if (installedLowerSet.has(dl)) {
          disabled.push(dep);
          stack.push(dl);          // recurse into the disabled dep's own deps
        } else {
          missing.push(dep);       // not installed; backend resolves its sub-deps
        }
      }
    }
    return { missing, disabled };
  };

  const allEntries: ModEntry[] = useMemo(() => game.installed_mods.map(im => {
    const meta = im.meta ?? null;
    const baseDeps = modDeps(im);
    const dependenciesMet = !im.enabled || baseDeps.every(d => enabledLowerSet.has(d.toLowerCase()));
    const name = meta?.name || im.filename.replace(/\.dll$/, '');
    return {
      id: im.id, name,
      installed: true, enabled: im.enabled, version: im.version,
      hasUpdate: updatesById.has(im.id),
      dependenciesMet,
      isLibrary: !!im.is_library,
      info: {
        id: im.id, name, description: meta?.description ?? '', filename: im.filename,
        source: { type: 'unknown', owner: '', repo: '', asset: '' },
        author: meta?.author, thumbnail: meta?.thumbnail, dependencies: baseDeps,
      },
    };
  }), [game.installed_mods, modDeps, enabledLowerSet, updatesById]);

  const modEntries = useMemo(
    () => allEntries.filter(e => installedMatchesFilter(e, filter)),
    [allEntries, filter],
  );
  const selectedEntry = modEntries[Math.min(selectedIndex, modEntries.length - 1)];

  // Transitive set of installed mods that depend (directly or indirectly) on any of
  // `rootIds` — the reverse mirror of collectEnableDeps. Disabling/removing a mod should
  // account for the whole downstream chain, not just direct dependents (X needs A, Y
  // needs X → disabling A reaches Y, not just X). With `requireEnabled`, only enabled
  // dependents are followed (a disabled mod is already inert); without it, every
  // installed dependent (e.g. for uninstall, which breaks dependents whether on or off).
  // Excludes the roots themselves; cycle-guarded via `seen`.
  const collectDependents = (rootIds: string[], requireEnabled: boolean): InstalledMod[] => {
    const rootSet = new Set(rootIds.map(i => i.toLowerCase()));
    const seen = new Set<string>();
    const result: InstalledMod[] = [];
    const stack = [...rootSet];
    while (stack.length > 0) {
      const target = stack.pop()!;
      for (const m of game.installed_mods) {
        const ml = m.id.toLowerCase();
        if (ml === target || seen.has(ml) || rootSet.has(ml)) continue;
        if (requireEnabled && !m.enabled) continue;
        if (!(m.meta?.dependencies ?? []).some(d => resolveDepId(d) === target)) continue;
        seen.add(ml);
        result.push(m);
        stack.push(ml);
      }
    }
    return result;
  };

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

  // After removing/disabling mods, offer to clean up library deps they orphaned.
  const cleanupOrphans = (removedIds: string[], mode: RemovalMode) =>
    showOrphanCleanup({ game, denylist, removedIds, mode, onRefresh, setBusy });

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
    const currentVersion = modByLowerId.get(mod.id.toLowerCase())?.version ?? null;
    const backedUp = await getBackedUpVersions(game.appid, mod.id);
    const dependents = collectDependents([mod.id], false);

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

  // Order ids so each mod's selected-group dependencies come before it.
  const topoEnableOrder = (ids: string[]): string[] => {
    const idSet = new Set(ids.map(i => i.toLowerCase()));
    const visited = new Set<string>();
    const result: string[] = [];
    const visit = (id: string) => {
      const lower = id.toLowerCase();
      if (visited.has(lower)) return;
      visited.add(lower);
      const im = modByLowerId.get(lower);
      for (const dep of modDeps(im)) {
        if (idSet.has(dep.toLowerCase())) {
          const depMod = modByLowerId.get(dep.toLowerCase());
          if (depMod) visit(depMod.id);
        }
      }
      result.push(id);
    };
    for (const id of ids) visit(id);
    return result;
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

  const bulkStepName = (id: string) => {
    const m = modByLowerId.get(id.toLowerCase());
    return m?.meta?.name ?? m?.filename ?? id;
  };

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
    // Every installed mod outside the selection that (transitively) depends on one being
    // uninstalled — enabled or not, since uninstall breaks them either way.
    const dependents = collectDependents(bulkUninstallTargets, false);

    const uninstallAll = async () => {
      let failed = 0;
      for (let i = 0; i < bulkUninstallTargets.length; i++) {
        const id = bulkUninstallTargets[i];
        const m = modByLowerId.get(id.toLowerCase());
        const name = m?.meta?.name ?? m?.filename ?? id;
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

  // Stable identities so memo(ModListItem) skips rows whose props didn't change on a
  // focus move. A ref keeps the toggle handler current without enumerating its many deps
  // — a wrong useCallback dep list here could act on stale enabled/dependency state.
  const handleToggleRef = useRef(handleToggleMod);
  handleToggleRef.current = handleToggleMod;
  const onItemToggle = useCallback((id: string, enable: boolean) => handleToggleRef.current(id, enable), []);
  const onItemFocus = useCallback((index: number) => setSelectedIndex(index), []);

  const queueFooter = useQueueFooterProps();

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
