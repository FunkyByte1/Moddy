import { ButtonItem, DialogButton, Focusable, PanelSection, PanelSectionRow, TextField, showModal } from '@decky/ui';
import { toaster } from '@decky/api';
import { FC, useState, useEffect, useMemo, useRef, CSSProperties } from 'react';
import { FixedSizeList } from 'react-window';

import {
  GameStatus,
  ThunderstorePackage,
  getThunderstoreCatalog,
  enqueueThunderstore,
  getBmiCatalog,
  enqueueBmi,
  getUnresolvedDependencies,
  uninstallMod,
  toggleMod,
  getBrowseDenylist,
} from '../types';
import { useDownloadQueue, isActiveStatus } from '../downloadQueue';
import { useQueueFooterProps } from '../components/DownloadQueueModal';
import DependentsModal from '../components/modals/DependentsModal';
import DependencyInstallModal from '../components/modals/DependencyInstallModal';
import MissingDependencyModal from '../components/modals/MissingDependencyModal';
import { showOrphanCleanup } from '../orphanCleanup';
import { CatalogSourceLabel } from '../components/CatalogSource';
import { BrowseFilter } from '../components/modals/BrowseFilterModal';
import { centerInView } from '../components/centerInView';

interface Props {
  game: GameStatus;
  onRefresh: () => Promise<void>;
  filter: BrowseFilter;
  onFilterButton: () => void;
  onCategoriesChange: (categories: string[]) => void;
  // Bumped by the Options-menu "Refresh Mod Catalog" action to force a re-fetch
  // after the backend cache has been invalidated.
  refreshKey?: number;
}

// Pixel sizes tuned for the Decky tab area at Steam Deck native res.
// Left panel hosts the virtualized list; right panel shows the focused mod's
// description and install action, mirroring the Mods tab split.
const ROW_HEIGHT = 52;
const LIST_HEIGHT = 480;
const LEFT_PANEL_WIDTH = 320;
const LIST_WIDTH = LEFT_PANEL_WIDTH - 16;

interface RowData {
  packages: ThunderstorePackage[];
  selectedIndex: number;
  installedIds: Set<string>;
  onSelect: (index: number) => void;
}

// Each row is a DialogButton styled as a list item. Spike 3 proved DialogButtons
// inside react-window are reachable by Steam's spatial nav — plain Focusables
// inside react-window are NOT, because their absolute-positioned wrappers don't
// register as nav targets. onFocus / onClick both update the selected index, so
// d-pad navigation and mouse clicks both work.
const Row: FC<{ index: number; style: CSSProperties; data: RowData }> = ({ index, style, data }) => {
  const pkg = data.packages[index];
  const isSelected = data.selectedIndex === index;
  const isInstalled = data.installedIds.has(pkg.full_name.toLowerCase());
  return (
    <div
      style={{ ...style, padding: '2px 0', boxSizing: 'border-box' }}
      onFocusCapture={(e) => { data.onSelect(index); centerInView(e.currentTarget); }}
    >
      <DialogButton
        onClick={() => data.onSelect(index)}
        style={{
          width: '100%',
          height: '100%',
          minHeight: 0,
          padding: '6px 8px',
          background: isSelected ? 'var(--gpColorHighlight1)' : 'rgba(255,255,255,0.04)',
          border: 'none',
          borderRadius: 4,
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          textAlign: 'left',
          color: 'inherit',
          fontWeight: 'normal',
          boxSizing: 'border-box',
        }}
      >
        <div
          style={{
            width: 32,
            height: 32,
            flexShrink: 0,
            borderRadius: 3,
            overflow: 'hidden',
            background: 'rgba(255,255,255,0.08)',
          }}
        >
          {pkg.latest.icon && (
            <img
              src={pkg.latest.icon}
              alt=""
              loading="lazy"
              style={{ width: '100%', height: '100%', display: 'block', objectFit: 'cover' }}
            />
          )}
        </div>
        <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
          <div
            style={{
              fontWeight: 600,
              fontSize: 13,
              lineHeight: '16px',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {pkg.name}
          </div>
          <div
            style={{
              fontSize: 10,
              lineHeight: '13px',
              color: 'var(--gpColorTextSecondary)',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {pkg.owner}
            {isInstalled && ' · installed'}
          </div>
        </div>
      </DialogButton>
    </div>
  );
};

const DetailPanel: FC<{
  pkg: ThunderstorePackage | null;
  installing: string | null;
  isInstalled: boolean;
  onInstall: (pkg: ThunderstorePackage) => void;
  onUninstall: (pkg: ThunderstorePackage) => void;
}> = ({ pkg, installing, isInstalled, onInstall, onUninstall }) => {
  if (!pkg) {
    return (
      <div style={{ color: 'var(--gpColorTextSecondary)', padding: 16 }}>
        Focus a mod on the left to see details.
      </div>
    );
  }
  const isBusy = installing === pkg.full_name;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12, padding: '12px 16px' }}>
      <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
        <div
          style={{
            width: 64,
            height: 64,
            flexShrink: 0,
            borderRadius: 4,
            overflow: 'hidden',
            background: 'rgba(255,255,255,0.08)',
          }}
        >
          {pkg.latest.icon && (
            <img
              src={pkg.latest.icon}
              alt=""
              style={{ width: '100%', height: '100%', display: 'block', objectFit: 'cover' }}
            />
          )}
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontWeight: 700, fontSize: 18, lineHeight: '22px' }}>{pkg.name}</div>
          <div style={{ fontSize: 12, color: 'var(--gpColorTextSecondary)', marginTop: 2 }}>
            by {pkg.owner} · v{pkg.latest.version_number}
            {pkg.rating_score > 0
              ? ` · ${pkg.rating_score} likes`
              : pkg.date_updated
                ? ` · updated ${pkg.date_updated.slice(0, 10)}`
                : ''}
          </div>
          {pkg.is_deprecated && (
            <div style={{ fontSize: 11, color: '#f8a623', marginTop: 4 }}>⚠ Deprecated</div>
          )}
        </div>
      </div>
      <PanelSection>
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            disabled={isBusy}
            onClick={() => (isInstalled ? onUninstall(pkg) : onInstall(pkg))}
          >
            {isBusy
              ? isInstalled
                ? 'Removing…'
                : 'Installing…'
              : isInstalled
                ? 'Uninstall'
                : 'Install'}
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>
      {pkg.latest.description && (
        <div style={{ fontSize: 13, lineHeight: '18px', color: 'var(--gpColorTextSecondary)' }}>
          {pkg.latest.description}
        </div>
      )}
      {pkg.latest.dependencies.length > 0 && (
        <div>
          <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 4 }}>Dependencies</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            {pkg.latest.dependencies.map(dep => (
              <div key={dep} style={{ fontSize: 11, color: 'var(--gpColorTextSecondary)' }}>
                {dep}
              </div>
            ))}
          </div>
        </div>
      )}
      {pkg.categories.length > 0 && (
        <div style={{ fontSize: 11, color: 'var(--gpColorTextSecondary)' }}>
          Categories: {pkg.categories.join(', ')}
        </div>
      )}
    </div>
  );
};

const BrowseTab: FC<Props> = ({ game, onRefresh, filter, onFilterButton, onCategoriesChange, refreshKey }) => {
  const isBmi = game.catalog_type === 'bmi';
  const [catalog, setCatalog] = useState<ThunderstorePackage[]>([]);
  const [denylist, setDenylist] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState('');
  const [installing, setInstalling] = useState<string | null>(null);
  // Optimistic "just clicked install" set, so the button shows busy instantly instead of waiting
  // for the enqueue round-trip + queue_state event — otherwise a quick double-press enqueues twice.
  const [pending, setPending] = useState<Set<string>>(new Set());
  const [selectedIndex, setSelectedIndex] = useState(0);
  const listRef = useRef<FixedSizeList | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const [data, deny] = await Promise.all([
          isBmi ? getBmiCatalog(game.appid) : getThunderstoreCatalog(game.appid),
          getBrowseDenylist(),
        ]);
        if (!cancelled) {
          setCatalog(data);
          setDenylist(new Set(deny.map(d => d.toLowerCase())));
        }
      } catch {
        if (!cancelled) {
          toaster.toast({ title: 'Moddy', body: 'Failed to fetch mod catalog' });
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [game.appid, refreshKey]);

  const installedIds = useMemo(
    () => new Set(game.installed_mods.map(m => m.id.toLowerCase())),
    [game.installed_mods]
  );

  // Mods/deps already covered by an in-flight or queued install: each job's own mod (`ref`)
  // plus the dependencies it declares (looked up in the catalog). The serial worker installs
  // a shared dependency only once — its cascade skips deps that are already recorded — so this
  // set lets the UI stop re-prompting for (and visually re-queuing) a dep that's about to exist
  // because an earlier job is still downloading it.
  const queue = useDownloadQueue();
  const queuedRefs = useMemo(
    () => new Set(queue.filter(j => isActiveStatus(j.status)).map(j => j.ref.toLowerCase())),
    [queue]
  );
  // Hand off the optimistic mark once the real job shows up in the queue (no busy-state flicker).
  useEffect(() => {
    setPending(p => {
      if (p.size === 0) return p;
      let changed = false;
      const next = new Set(p);
      for (const fn of p) if (queuedRefs.has(fn.toLowerCase())) { next.delete(fn); changed = true; }
      return changed ? next : p;
    });
  }, [queuedRefs]);
  const pendingDepIds = useMemo(() => {
    const ids = new Set<string>();
    for (const j of queue) {
      if (!isActiveStatus(j.status)) continue;
      ids.add(j.ref.toLowerCase());
      const p = catalog.find(c => c.full_name.toLowerCase() === j.ref.toLowerCase());
      for (const d of p?.latest.dependencies ?? []) {
        ids.add(d.split('-').slice(0, -1).join('-').toLowerCase());
      }
    }
    return ids;
  }, [queue, catalog]);

  // Library categories ("Libraries"/"API") are governed by the dedicated
  // "Show Libraries" toggle, so they're kept out of the generic category list to
  // avoid two controls fighting over the same mods.
  const libraryCategorySet = useMemo(
    () => new Set((game.library_categories ?? []).map(c => c.toLowerCase())),
    [game.library_categories]
  );

  const isLibraryPkg = (p: ThunderstorePackage) =>
    p.categories.some(c => libraryCategorySet.has(c.toLowerCase()));

  // All non-library categories present in the (non-denylisted) catalog, surfaced to
  // the parent so the filter modal can list them.
  const categories = useMemo(() => {
    const set = new Set<string>();
    for (const p of catalog) {
      if (denylist.has(p.full_name.toLowerCase())) continue;
      for (const c of p.categories) {
        if (!libraryCategorySet.has(c.toLowerCase())) set.add(c);
      }
    }
    return [...set].sort();
  }, [catalog, denylist, libraryCategorySet]);

  useEffect(() => {
    onCategoriesChange(categories);
  }, [categories, onCategoriesChange]);

  const filtered = useMemo(() => {
    const q = query.toLowerCase().trim();
    let list = catalog.filter(p => {
      if (denylist.has(p.full_name.toLowerCase())) return false;
      if (p.is_deprecated && !filter.showDeprecated) return false;
      if (p.has_nsfw_content && !filter.showNsfw) return false;
      if (filter.hideLibraries && isLibraryPkg(p)) return false;
      const isInstalled = installedIds.has(p.full_name.toLowerCase());
      if (isInstalled && !filter.installed) return false;
      if (!isInstalled && !filter.notInstalled) return false;
      if (filter.categories.length > 0 && !p.categories.some(c => filter.categories.includes(c)))
        return false;
      return true;
    });
    if (q) {
      list = list.filter(
        p =>
          p.full_name.toLowerCase().includes(q) ||
          p.latest.description.toLowerCase().includes(q)
      );
    }
    switch (filter.sortBy) {
      case 'name': list.sort((a, b) => a.name.localeCompare(b.name)); break;
      // ISO date strings sort lexically, newest first.
      case 'updated': list.sort((a, b) => (b.date_updated ?? '').localeCompare(a.date_updated ?? '')); break;
      case 'rating':
      default: list.sort((a, b) => b.rating_score - a.rating_score); break;
    }
    return list;
  }, [catalog, query, denylist, filter, installedIds, libraryCategorySet]);

  // Reset selection when the filtered list changes (search edits, filter
  // changes) so the detail panel never points at a stale index that's now out
  // of bounds.
  useEffect(() => {
    setSelectedIndex(0);
    listRef.current?.scrollToItem(0);
  }, [query, filter]);

  // Installs are handed to the background download queue (the pill / QAM show progress);
  // the queue's completion is what refreshes the installed list + toasts (see ModPage), so
  // this just enqueues and returns. Uninstall stays inline (handleUninstall, below).
  const runInstall = (pkg: ThunderstorePackage, withDeps = true, allowMissing = false) => {
    setPending(p => new Set(p).add(pkg.full_name));
    const done = isBmi
      ? enqueueBmi(game.appid, pkg.full_name, pkg.name, null)
      : enqueueThunderstore(game.appid, pkg.full_name, pkg.name, null, withDeps, allowMissing);
    done.catch(() => {
      setPending(p => { const n = new Set(p); n.delete(pkg.full_name); return n; });
      toaster.toast({ title: 'Moddy', body: `Failed to queue ${pkg.name}` });
    });
  };

  const handleInstall = async (pkg: ThunderstorePackage) => {
    // Thunderstore only: a declared dependency might not be in the catalog (can't auto-install).
    // Check up front (the backend refreshes once to rule out a stale cache) and, if so, let the
    // user install anyway without it rather than failing the whole install.
    if (!isBmi) {
      const unresolved = await getUnresolvedDependencies(game.appid, pkg.full_name).catch(() => [] as string[]);
      if (unresolved.length > 0) {
        showModal(
          <MissingDependencyModal
            modName={pkg.name}
            missingNames={unresolved}
            onInstallAnyway={close => { close(); runInstall(pkg, true, true); }}
          />
        );
        return;
      }
    }
    // Thunderstore deps are versioned strings ("Owner-Mod-1.2.3"); the install id is the
    // un-versioned full_name. Only prompt for deps that aren't already installed — the
    // backend cascades them on install, so this modal is a confirmation gate (like the
    // Installed tab's enable-deps prompt), not a separate install path. (BMI items carry no
    // deps, so this is effectively a no-op gate for them and they install directly.)
    // Drop denylisted packages (modloaders / mod-manager apps): a mod's declared dependency on
    // e.g. BepInExPack is satisfied by the Mod Loader tab, not by installing it as a plugin — so
    // it must never appear in the install-deps prompt (matching the Browse panel's dep list).
    const missingDeps = pkg.latest.dependencies
      .map(d => d.split('-').slice(0, -1).join('-'))
      .filter(id => id && !denylist.has(id.toLowerCase())
        && !installedIds.has(id.toLowerCase()) && !pendingDepIds.has(id.toLowerCase()));

    if (missingDeps.length > 0) {
      const depNames = missingDeps.map(id =>
        catalog.find(p => p.full_name.toLowerCase() === id.toLowerCase())?.name ?? id
      );
      showModal(
        <DependencyInstallModal
          modName={pkg.name}
          dependencyNames={depNames}
          onInstall={close => { close(); runInstall(pkg, true); }}
          onSkip={close => { close(); runInstall(pkg, false); }}
        />
      );
      return;
    }
    runInstall(pkg);
  };

  const handleUninstall = (pkg: ThunderstorePackage) => {
    // Installed mods record their deps as versioned Thunderstore strings
    // ("Owner-Mod-1.2.3"); the install id drops the trailing version segment.
    const fn = pkg.full_name.toLowerCase();
    const dependents = game.installed_mods.filter(m =>
      (m.meta?.dependencies ?? []).some(
        d => d.split('-').slice(0, -1).join('-').toLowerCase() === fn
      )
    );

    const run = async (depAction: 'disable' | 'delete' | 'none') => {
      setInstalling(pkg.full_name);
      try {
        if (depAction === 'delete') {
          for (const dep of dependents) await uninstallMod(game.appid, dep.id);
        } else if (depAction === 'disable') {
          for (const dep of dependents) await toggleMod(game.appid, dep.id, false);
        }
        const ok = await uninstallMod(game.appid, pkg.full_name);
        toaster.toast({
          title: 'Moddy',
          body: ok ? `Uninstalled ${pkg.name}` : `Failed to uninstall ${pkg.name}`,
        });
        await onRefresh();
      } finally {
        setInstalling(null);
      }
      const removedIds = depAction === 'delete'
        ? [pkg.full_name, ...dependents.map(d => d.id)]
        : [pkg.full_name];
      showOrphanCleanup({
        game, denylist: new Set<string>(), removedIds, mode: 'uninstall',
        onRefresh, setBusy: b => setInstalling(b ? pkg.full_name : null),
      });
    };

    if (dependents.length > 0) {
      showModal(
        <DependentsModal
          dependentNames={dependents.map(m => m.meta?.name ?? m.filename.replace(/\.dll$/, '') ?? m.id)}
          onDisable={close => { close(); run('disable'); }}
          onIgnore={close => { close(); run('none'); }}
          onDelete={close => { close(); run('delete'); }}
        />
      );
      return;
    }
    run('none');
  };

  const itemData: RowData = useMemo(
    () => ({ packages: filtered, selectedIndex, installedIds, onSelect: setSelectedIndex }),
    [filtered, selectedIndex, installedIds]
  );

  const selectedPkg = filtered[selectedIndex] ?? null;
  const selectedIsInstalled = selectedPkg
    ? installedIds.has(selectedPkg.full_name.toLowerCase())
    : false;

  // A mod whose job is queued/downloading reads as "busy" on its detail button, same as the
  // old inline install. `installing` (local) still covers the inline uninstall path.
  const selectedBusy = !!installing && installing === selectedPkg?.full_name
    || (!!selectedPkg && (pending.has(selectedPkg.full_name) || queuedRefs.has(selectedPkg.full_name.toLowerCase())));

  // Always render the Focusable layout, even during loading. If the loading
  // branch returns a bare div with no focusable children, Steam's autoFocus
  // misses on tab entry and the user ends up with focus stranded on the
  // previous tab — every input then routes back to that tab.
  let listSlot;
  if (loading) {
    listSlot = (
      <div style={{ padding: 16, color: 'var(--gpColorTextSecondary)' }}>
        Loading catalog…
      </div>
    );
  } else if (catalog.length === 0) {
    listSlot = (
      <div style={{ padding: 16, color: 'var(--gpColorTextSecondary)' }}>
        Catalog unavailable. Check network and try again.
      </div>
    );
  } else if (filtered.length === 0) {
    listSlot = (
      <div style={{ padding: 16, color: 'var(--gpColorTextSecondary)' }}>
        No mods match.
      </div>
    );
  } else {
    listSlot = (
      <FixedSizeList
        ref={listRef}
        height={LIST_HEIGHT}
        width={LIST_WIDTH}
        itemCount={filtered.length}
        itemSize={ROW_HEIGHT}
        itemData={itemData}
      >
        {Row}
      </FixedSizeList>
    );
  }

  return (
    <Focusable
      style={{ display: 'flex', height: '100%', overflow: 'hidden' }}
      {...useQueueFooterProps()}
      onSecondaryButton={onFilterButton}
      onSecondaryActionDescription="Filter"
    >
      <Focusable
        style={{
          width: LEFT_PANEL_WIDTH,
          borderRight: '1px solid var(--gpColorSeparator)',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        <div style={{ padding: 8 }}>
          <TextField
            label="Search"
            value={query}
            onChange={e => setQuery(e.target.value)}
            // Enter (R2 on the on-screen keyboard) dismisses the keyboard by blurring the field.
            onKeyDown={e => { if (e.key === 'Enter') e.currentTarget.blur(); }}
          />
          <CatalogSourceLabel source={isBmi ? 'bmi' : 'thunderstore'} />
          <div style={{ marginTop: 4, fontSize: 11, color: 'var(--gpColorTextSecondary)' }}>
            {loading
              ? 'Loading…'
              : filtered.length === catalog.length
                ? `${filtered.length} mods`
                : `${filtered.length} of ${catalog.length}`}
          </div>
        </div>
        {listSlot}
      </Focusable>
      <Focusable style={{ flex: 1, overflowY: 'auto', paddingBottom: 60 }}>
        <DetailPanel
          pkg={selectedPkg}
          installing={selectedBusy ? (selectedPkg?.full_name ?? null) : null}
          isInstalled={selectedIsInstalled}
          onInstall={handleInstall}
          onUninstall={handleUninstall}
        />
      </Focusable>
    </Focusable>
  );
};

export default BrowseTab;
