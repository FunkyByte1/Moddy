import { ButtonItem, DialogButton, Focusable, PanelSection, PanelSectionRow, TextField, showModal } from '@decky/ui';
import { toaster } from '@decky/api';
import { FC, useState, useEffect, useMemo, useRef, useCallback, CSSProperties } from 'react';
import { FixedSizeList } from 'react-window';

import {
  GameStatus,
  ThunderstorePackage,
  getThunderstoreCatalog,
  enqueueThunderstore,
  getBmiCatalog,
  enqueueBmi,
  getUnresolvedDependencies,
  getBrowseDenylist,
} from '../types';
import { useQueueFooterProps } from '../components/DownloadQueueModal';
import DependencyChecklistModal from '../components/modals/DependencyChecklistModal';
import { CatalogSourceLabel } from '../components/CatalogSource';
import { BrowseFilter } from '../components/modals/BrowseFilterModal';
import { centerInView } from '../components/centerInView';
import { transitiveCatalogDeps } from '../browseDeps';
import { stripVersion } from '../modGraph';
import { useBrowseInstall } from './browse/useBrowseInstall';
import { useBrowseUninstall } from './browse/useBrowseUninstall';

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
  // Pressing A on a row jumps focus to the detail panel's install button.
  onActivate: () => void;
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
        onClick={() => { data.onSelect(index); data.onActivate(); }}
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
  // Number of resolvable, not-yet-installed dependencies — when > 0 (and not installed), the
  // "Install with options…" escape hatch is offered alongside the plain (install-everything) button.
  missingDepCount: number;
  onInstall: (pkg: ThunderstorePackage) => void;
  onInstallWithOptions: (pkg: ThunderstorePackage) => void;
  onUninstall: (pkg: ThunderstorePackage) => void;
}> = ({ pkg, installing, isInstalled, missingDepCount, onInstall, onInstallWithOptions, onUninstall }) => {
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
        {!isInstalled && missingDepCount > 0 && (
          <PanelSectionRow>
            <ButtonItem layout="below" disabled={isBusy} onClick={() => onInstallWithOptions(pkg)}>
              Install with options…
            </ButtonItem>
          </PanelSectionRow>
        )}
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
  const [selectedIndex, setSelectedIndex] = useState(0);
  const listRef = useRef<FixedSizeList | null>(null);
  const listOuterRef = useRef<HTMLDivElement | null>(null);

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

  // Shared install busy-state (optimistic pending → queue handoff) + the uninstall flow.
  const { setInstalling, isBusy, addPending, removePending, pending, queuedRefs } =
    useBrowseInstall('queue');
  const uninstall = useBrowseUninstall(game, onRefresh, setInstalling);

  // Mods/deps already covered by an in-flight or queued install: each in-flight mod plus its full
  // (transitive) dependency tree, looked up in the catalog. The serial worker installs a shared
  // dependency only once — so this set lets the UI stop re-prompting for (and visually re-queuing) a
  // dep that's about to exist because an earlier job is still downloading it.
  const pendingDepIds = useMemo(() => {
    // Mods being installed right now: active queue jobs (queuedRefs) plus just-clicked refs not yet
    // in the queue (the optimistic `pending` set covers the brief enqueue round-trip).
    // transitiveCatalogDeps walks each one's full dependency tree, so the install-deps prompt is
    // suppressed for anything an in-flight install already covers (directly or transitively).
    const inFlight = new Set<string>(queuedRefs);
    for (const fn of pending) inFlight.add(fn.toLowerCase());
    return transitiveCatalogDeps(catalog, inFlight);
  }, [queuedRefs, pending, catalog]);

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
    addPending(pkg.full_name);
    const done = isBmi
      ? enqueueBmi(game.appid, pkg.full_name, pkg.name, null)
      : enqueueThunderstore(game.appid, pkg.full_name, pkg.name, null, withDeps, allowMissing);
    done.catch(() => {
      removePending(pkg.full_name);
      toaster.toast({ title: 'Moddy', body: `Failed to queue ${pkg.name}` });
    });
  };

  // A mod's resolvable, not-yet-installed dependencies, as checklist entries (with the version the
  // mod pins). Thunderstore deps are versioned strings ("Owner-Mod-1.2.3"); the install id is the
  // un-versioned full_name. Denylisted packages (modloaders satisfied by the Mod Loader tab) and
  // deps already installed or in-flight are dropped — they never need a choice. BMI items carry no
  // deps, so this is empty for them.
  const depEntries = (pkg: ThunderstorePackage) =>
    pkg.latest.dependencies
      .map(d => ({ id: stripVersion(d), version: d.split('-').slice(-1)[0] }))
      .filter(e => e.id && !denylist.has(e.id.toLowerCase())
        && !installedIds.has(e.id.toLowerCase()) && !pendingDepIds.has(e.id.toLowerCase()))
      .map(e => ({
        id: e.id,
        version: e.version,
        name: catalog.find(p => p.full_name.toLowerCase() === e.id.toLowerCase())?.name ?? e.id,
      }));

  // Plain install: pull the mod and all its dependencies, no prompt. If a declared dependency
  // isn't in the catalog (can't be auto-installed), don't block — install the mod anyway and warn
  // via a toast rather than failing or interrupting. Per-dependency control lives behind the
  // "Install with options…" button (handleInstallWithOptions).
  const handleInstall = async (pkg: ThunderstorePackage) => {
    if (!isBmi) {
      const unresolved = await getUnresolvedDependencies(game.appid, pkg.full_name).catch(() => [] as string[]);
      if (unresolved.length > 0) {
        toaster.toast({
          title: 'Moddy',
          body: `Installing ${pkg.name} — ${unresolved.length} ${unresolved.length === 1 ? "dependency isn't" : "dependencies aren't"} available and won't be installed`,
        });
        runInstall(pkg, true, true);
        return;
      }
    }
    runInstall(pkg);
  };

  // The "special" path: install the mod alone, then enqueue only the dependencies the user kept
  // (each pulls its own subtree). Lets a mod be installed while declining a bad/outdated dep it
  // declares, without losing the others.
  const installSelective = (pkg: ThunderstorePackage, selectedIds: string[]) => {
    runInstall(pkg, false, true);
    for (const depId of selectedIds) {
      const depPkg = catalog.find(p => p.full_name.toLowerCase() === depId.toLowerCase());
      addPending(depId);
      enqueueThunderstore(game.appid, depId, depPkg?.name ?? depId, null, true, true).catch(() => {
        removePending(depId);
        toaster.toast({ title: 'Moddy', body: `Failed to queue ${depPkg?.name ?? depId}` });
      });
    }
  };

  const handleInstallWithOptions = (pkg: ThunderstorePackage) => {
    const deps = depEntries(pkg);
    if (deps.length === 0) { handleInstall(pkg); return; }
    showModal(
      <DependencyChecklistModal
        modName={pkg.name}
        dependencies={deps}
        onInstall={(selected, close) => { close(); installSelective(pkg, selected); }}
      />
    );
  };

  const handleUninstall = (pkg: ThunderstorePackage) => {
    // Thunderstore deps are recorded as versioned full_names ("Owner-Mod-1.2.3"), so strip the
    // version to match this mod's install id — unlike Nexus/Workshop, whose recorded deps are
    // already full install ids. The shared hook handles the rest (dependents prompt + orphan sweep).
    const fn = pkg.full_name.toLowerCase();
    const dependents = game.installed_mods.filter(m =>
      (m.meta?.dependencies ?? []).some(d => d.split('-').slice(0, -1).join('-').toLowerCase() === fn),
    );
    uninstall({ uninstallId: pkg.full_name, title: pkg.name, busyKey: pkg.full_name, dependents });
  };

  // Pressing A on a left-list row jumps focus to the detail panel's install button (matching the
  // Nexus/Workshop tabs), so you don't have to navigate right after selecting. Stable identity so
  // it doesn't bust the itemData memo.
  const detailRef = useRef<HTMLDivElement>(null);
  const focusDetail = useCallback(() => {
    (detailRef.current?.querySelector('button, [tabindex]') as HTMLElement | null)?.focus();
  }, []);

  // After submitting a search on the on-screen keyboard (Enter/R2 blurs the field), drop focus onto
  // the first result so the user can navigate the list straight away instead of being left on
  // nothing. Filtering here is synchronous, so by Enter the list already reflects the query; scroll
  // to the top first to guarantee row 0 is rendered (virtualized), then focus its button next frame.
  const focusFirstRow = useCallback(() => {
    listRef.current?.scrollToItem(0);
    requestAnimationFrame(() => {
      (listOuterRef.current?.querySelector('button') as HTMLElement | null)?.focus();
    });
  }, []);

  const itemData: RowData = useMemo(
    () => ({ packages: filtered, selectedIndex, installedIds, onSelect: setSelectedIndex, onActivate: focusDetail }),
    [filtered, selectedIndex, installedIds, focusDetail]
  );

  const selectedPkg = filtered[selectedIndex] ?? null;
  const selectedIsInstalled = selectedPkg
    ? installedIds.has(selectedPkg.full_name.toLowerCase())
    : false;

  // A mod whose job is queued/downloading (or just-clicked, or mid-uninstall) reads as "busy" on its
  // detail button — the shared queue busy-state.
  const selectedBusy = !!selectedPkg && isBusy(selectedPkg.full_name);

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
        outerRef={listOuterRef}
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
      {...useQueueFooterProps(game.appid)}
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
            // Enter (R2 on the on-screen keyboard) dismisses the keyboard by blurring the field,
            // then moves focus to the first result so the list is ready to navigate.
            onKeyDown={e => { if (e.key === 'Enter') { e.currentTarget.blur(); focusFirstRow(); } }}
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
      <Focusable ref={detailRef} style={{ flex: 1, overflowY: 'auto', paddingBottom: 60 }}>
        <DetailPanel
          pkg={selectedPkg}
          installing={selectedBusy ? (selectedPkg?.full_name ?? null) : null}
          isInstalled={selectedIsInstalled}
          missingDepCount={selectedPkg && !selectedIsInstalled ? depEntries(selectedPkg).length : 0}
          onInstall={handleInstall}
          onInstallWithOptions={handleInstallWithOptions}
          onUninstall={handleUninstall}
        />
      </Focusable>
    </Focusable>
  );
};

export default BrowseTab;
