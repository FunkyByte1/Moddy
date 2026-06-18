import { ButtonItem, Focusable, PanelSection, PanelSectionRow, ScrollPanelGroup, Spinner, TextField, showModal } from '@decky/ui';
import { toaster } from '@decky/api';
import { FC, useState, useEffect, useMemo, useRef } from 'react';

import {
  GameStatus, ThunderstorePackage,
  getNexusCatalog, enqueueNexus, uninstallMod, toggleMod,
} from '../types';
import { useDownloadQueue, isActiveStatus } from '../downloadQueue';
import { useQueueFooterProps } from '../components/DownloadQueueModal';
import { NexusFilter } from '../components/modals/NexusFilterModal';
import DependentsModal from '../components/modals/DependentsModal';
import { showOrphanCleanup } from '../orphanCleanup';
import { CatalogSourceLabel } from '../components/CatalogSource';
import { centerInView } from '../components/centerInView';

// Steam's gamepad-scrollable container (scrolls with the right stick). Falls back to a
// plain Focusable if the internal lookup ever fails, so it never crashes.
const ScrollArea = (ScrollPanelGroup ?? Focusable) as FC<any>;

// Matches the backend Nexus page size; fewer than a full page means we've reached the end.
const PAGE_FULL = 25;
const LEFT_PANEL_WIDTH = 320;

const Row: FC<{
  item: ThunderstorePackage; selected: boolean; installed: boolean;
  onSelect: () => void; onActivate: () => void; innerRef?: (el: HTMLDivElement | null) => void;
}> = ({ item, selected, installed, onSelect, onActivate, innerRef }) => (
  // A plain Focusable (like the Workshop/Installed rows) so it gets Steam's focus-ring border.
  <Focusable
    ref={innerRef}
    onFocus={(e) => { onSelect(); centerInView(e.currentTarget); }}
    onActivate={onActivate}
    style={{
      display: 'flex', alignItems: 'center', gap: 8, padding: '8px',
      borderRadius: 4, marginBottom: 2, cursor: 'pointer', outline: 'none',
      background: selected ? 'var(--gpColorHighlight1)' : 'transparent',
    }}
  >
    <div style={{ width: 32, height: 32, flexShrink: 0, borderRadius: 3, overflow: 'hidden', background: 'rgba(255,255,255,0.08)' }}>
      {item.latest.icon && <img src={item.latest.icon} alt="" loading="lazy" style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }} />}
    </div>
    <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
      <div style={{ fontWeight: 600, fontSize: 13, lineHeight: '16px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {item.name}
      </div>
      <div style={{ fontSize: 10, lineHeight: '13px', color: 'var(--gpColorTextSecondary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {item.owner}{installed && ' · installed'}
      </div>
    </div>
  </Focusable>
);

const NexusBrowseTab: FC<{
  game: GameStatus;
  onRefresh: () => Promise<void>;
  filter: NexusFilter;
  onFilterButton: () => void;
  // False until the parent's NSFW default-on seed has resolved. Holding the first fetch
  // until then avoids a wasted non-adult request followed by an adult re-fetch — Nexus
  // rate limits are strict, so the initial query must use the final include_adult value.
  ready: boolean;
}> = ({ game, onRefresh, filter, onFilterButton, ready }) => {
  const [search, setSearch] = useState('');
  const [debounced, setDebounced] = useState('');
  const [items, setItems] = useState<ThunderstorePackage[]>([]);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [installing, setInstalling] = useState<string | null>(null);
  // Optimistic "just clicked install" set, so the button shows busy instantly instead of waiting
  // for the enqueue round-trip + queue_state event — otherwise a quick double-press enqueues twice.
  const [pending, setPending] = useState<Set<string>>(new Set());
  const [selectedIndex, setSelectedIndex] = useState(0);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(search.trim()), 350);
    return () => clearTimeout(t);
  }, [search]);

  useEffect(() => {
    // Wait for the parent's NSFW seed so the first query uses the final include_adult.
    if (!ready) return;
    let cancelled = false;
    (async () => {
      setLoading(true); setSelectedIndex(0);
      try {
        // Adult content is a server-side filter, so toggling Show NSFW re-fetches page 1.
        const data = await getNexusCatalog(game.appid, debounced, 1, filter.showNsfw);
        if (!cancelled) { setItems(data); setPage(1); setHasMore(data.length >= PAGE_FULL); }
      } catch {
        if (!cancelled) toaster.toast({ title: 'Moddy', body: 'Failed to load Nexus catalog' });
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [game.appid, debounced, filter.showNsfw, ready]);

  const loadMore = async () => {
    if (loadingMore || !hasMore) return;
    setLoadingMore(true);
    try {
      const next = page + 1;
      const data = await getNexusCatalog(game.appid, debounced, next, filter.showNsfw);
      const have = new Set(items.map(i => i.full_name));
      setItems(prev => [...prev, ...data.filter(i => !have.has(i.full_name))]);
      setPage(next);
      setHasMore(data.length >= PAGE_FULL);
    } catch {
      toaster.toast({ title: 'Moddy', body: 'Failed to load more' });
    } finally {
      setLoadingMore(false);
    }
  };

  // Load more via a button, but move focus back into the list (to the last mod) once
  // it's pressed — otherwise focus stays on the button and "up" jumps to the bottom.
  const rowRefs = useRef<Map<number, HTMLDivElement>>(new Map());
  const [pendingFocus, setPendingFocus] = useState<number | null>(null);

  useEffect(() => {
    if (pendingFocus == null) return;
    const el = rowRefs.current.get(pendingFocus);
    const focusable = (el?.querySelector('button, [tabindex]') as HTMLElement | null) ?? el;
    focusable?.focus();
    setSelectedIndex(pendingFocus);
    setPendingFocus(null);
  }, [items, pendingFocus]);

  const handleLoadMore = async () => {
    const lastMod = Math.max(0, visible.length - 1);
    await loadMore();
    setPendingFocus(lastMod);
  };

  // Pressing A on a mod (or navigating right) jumps focus to the detail panel's action
  // button; pressing B in the detail returns to the selected mod in the list.
  const detailRef = useRef<HTMLDivElement>(null);
  const focusDetail = () => {
    (detailRef.current?.querySelector('button, [tabindex]') as HTMLElement | null)?.focus();
  };
  const focusSelectedRow = () => {
    const el = rowRefs.current.get(selectedIndex);
    ((el?.querySelector('button, [tabindex]') as HTMLElement | null) ?? el)?.focus();
  };

  const installedIds = useMemo(
    () => new Set(game.installed_mods.map(m => m.id.toLowerCase())),
    [game.installed_mods],
  );
  const isInstalled = (it: ThunderstorePackage) => installedIds.has(it.full_name.toLowerCase());

  // Install-status filter is applied client-side over the loaded pages (NSFW is handled
  // server-side via the re-fetch above). `visible` is what the list renders and indexes.
  const visible = useMemo(
    () => items.filter(it => {
      const inst = installedIds.has(it.full_name.toLowerCase());
      if (inst && !filter.installed) return false;
      if (!inst && !filter.notInstalled) return false;
      return true;
    }),
    [items, installedIds, filter.installed, filter.notInstalled],
  );

  // Keep the selection in range when the install-status filter shrinks the list.
  useEffect(() => { setSelectedIndex(0); }, [filter.installed, filter.notInstalled]);

  const selected = visible[Math.min(selectedIndex, visible.length - 1)] ?? null;

  // A mod whose job is queued/downloading/parked reads as busy. `installing` (local) still covers
  // the inline uninstall path below.
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
  const isBusy = (it: ThunderstorePackage) =>
    installing === it.full_name || pending.has(it.full_name) || queuedRefs.has(it.full_name.toLowerCase());

  // Hand the install to the background queue. Variant selection and any failure are surfaced via
  // the queue (the variant prompt pops from ModPage when the job parks); ModPage refreshes + toasts
  // on completion. Uninstall stays inline below.
  const handleInstall = (it: ThunderstorePackage) => {
    setPending(p => new Set(p).add(it.full_name));
    enqueueNexus(game.appid, it.full_name, it.name, null).catch(() => {
      setPending(p => { const n = new Set(p); n.delete(it.full_name); return n; });
      toaster.toast({ title: 'Moddy', body: `Failed to queue ${it.name}` });
    });
  };

  const handleUninstall = (it: ThunderstorePackage) => {
    const id = it.full_name;
    const dependents = game.installed_mods.filter(m => (m.meta?.dependencies ?? []).includes(id));
    const run = async (action: 'disable' | 'delete' | 'none') => {
      setInstalling(it.full_name);
      try {
        if (action === 'delete') for (const d of dependents) await uninstallMod(game.appid, d.id);
        else if (action === 'disable') for (const d of dependents) await toggleMod(game.appid, d.id, false);
        const ok = await uninstallMod(game.appid, id);
        toaster.toast({ title: 'Moddy', body: ok ? `Removed ${it.name}` : `Failed to remove ${it.name}` });
        await onRefresh();
      } finally { setInstalling(null); }
      const removedIds = action === 'delete'
        ? [id, ...dependents.map(d => d.id)]
        : [id];
      showOrphanCleanup({
        game, denylist: new Set<string>(), removedIds, mode: 'uninstall',
        onRefresh, setBusy: b => setInstalling(b ? it.full_name : null),
      });
    };
    if (dependents.length > 0) {
      showModal(
        <DependentsModal
          dependentNames={dependents.map(m => m.meta?.name ?? m.filename ?? m.id)}
          onDisable={c => { c(); run('disable'); }}
          onIgnore={c => { c(); run('none'); }}
          onDelete={c => { c(); run('delete'); }}
        />
      );
      return;
    }
    run('none');
  };

  return (
    <Focusable
      style={{ display: 'flex', height: '100%', overflow: 'hidden' }}
      {...useQueueFooterProps()}
      onSecondaryButton={onFilterButton}
      onSecondaryActionDescription="Filter"
    >
      <Focusable style={{ width: LEFT_PANEL_WIDTH, borderRight: '1px solid var(--gpColorSeparator)', display: 'flex', flexDirection: 'column' }}>
        <div style={{ padding: 8 }}>
          <TextField label="Search Nexus" value={search} onChange={e => setSearch(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') e.currentTarget.blur(); }} />
          <CatalogSourceLabel source="nexus" />
          <div style={{ marginTop: 6, minHeight: 16, fontSize: 11, color: 'var(--gpColorTextSecondary)' }}>
            {loading ? 'Loading…' : visible.length > 0 ? `${visible.length} mod${visible.length === 1 ? '' : 's'}` : ''}
          </div>
        </div>
        <Focusable style={{ flex: 1, overflowY: 'auto', padding: '0 8px 60px' }}>
          {loading ? (
            <div style={{ padding: 24, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8, color: 'var(--gpColorTextSecondary)' }}>
              <Spinner style={{ width: 28, height: 28 }} />
              <div style={{ fontSize: 12 }}>Loading catalog…</div>
            </div>
          ) : items.length === 0 ? (
            <div style={{ padding: 16, color: 'var(--gpColorTextSecondary)' }}>
              {debounced ? 'No matches.' : 'Catalog unavailable — set your Nexus API key in the Moddy panel and check your network.'}
            </div>
          ) : visible.length === 0 ? (
            <div style={{ padding: 16, color: 'var(--gpColorTextSecondary)' }}>
              No mods match the filter.
            </div>
          ) : (
            <>
              {visible.map((it, i) => (
                <Row key={it.full_name} item={it} selected={i === selectedIndex} installed={isInstalled(it)}
                  onSelect={() => setSelectedIndex(i)} onActivate={focusDetail}
                  innerRef={el => { if (el) rowRefs.current.set(i, el); else rowRefs.current.delete(i); }} />
              ))}
              {hasMore && (
                <div style={{ padding: '8px 0' }}>
                  <ButtonItem layout="below" disabled={loadingMore} onClick={handleLoadMore}>
                    {loadingMore ? 'Loading…' : 'Load more'}
                  </ButtonItem>
                </div>
              )}
            </>
          )}
        </Focusable>
      </Focusable>

      <ScrollArea focusable={false} style={{ flex: 1, minHeight: 0, height: '100%' }}>
        {!selected ? (
          <div style={{ color: 'var(--gpColorTextSecondary)', padding: 16 }}>Focus a mod on the left to see details.</div>
        ) : (
          <Focusable
            ref={detailRef}
            noFocusRing
            onGamepadFocus={focusDetail}
            onCancelButton={focusSelectedRow}
            style={{ display: 'flex', flexDirection: 'column', gap: 12, padding: '12px 16px 60px' }}
          >
            <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
              <div style={{ width: 80, height: 80, flexShrink: 0, borderRadius: 4, overflow: 'hidden', background: 'rgba(255,255,255,0.08)' }}>
                {selected.latest.icon && <img src={selected.latest.icon} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }} />}
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontWeight: 700, fontSize: 18, lineHeight: '22px' }}>{selected.name}</div>
                <div style={{ fontSize: 12, color: 'var(--gpColorTextSecondary)', marginTop: 2 }}>
                  by {selected.owner}
                  {selected.latest.version_number ? ` · v${selected.latest.version_number}` : ''}
                  {selected.date_updated ? ` · updated ${selected.date_updated.slice(0, 10)}` : ''}
                </div>
              </div>
            </div>
            <PanelSection>
              <PanelSectionRow>
                <ButtonItem
                  layout="below"
                  disabled={isBusy(selected)}
                  onClick={() => (isInstalled(selected) ? handleUninstall(selected) : handleInstall(selected))}
                >
                  {isBusy(selected)
                    ? (isInstalled(selected) ? 'Removing…' : 'Installing…')
                    : isInstalled(selected) ? 'Uninstall' : 'Install'}
                </ButtonItem>
              </PanelSectionRow>
            </PanelSection>
            {selected.latest.description && (
              <div style={{ fontSize: 13, lineHeight: '18px', color: 'var(--gpColorTextSecondary)', whiteSpace: 'pre-wrap' }}>
                {selected.latest.description}
              </div>
            )}
          </Focusable>
        )}
      </ScrollArea>
    </Focusable>
  );
};

export default NexusBrowseTab;
