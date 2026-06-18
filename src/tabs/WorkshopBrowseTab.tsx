import { ButtonItem, Focusable, PanelSection, PanelSectionRow, ScrollPanelGroup, Spinner, TextField, showModal } from '@decky/ui';
import { toaster } from '@decky/api';
import { FC, useState, useEffect, useMemo, useRef } from 'react';

import {
  GameStatus, WorkshopCatalogItem,
  getWorkshopCatalog, getWorkshopRequiredItems, installWorkshopTree, uninstallMod, toggleMod,
  workshopModId, fileIdForMod,
} from '../types';
import DependentsModal from '../components/modals/DependentsModal';
import DependencyInstallModal from '../components/modals/DependencyInstallModal';
import { showOrphanCleanup } from '../orphanCleanup';
import { CatalogSourceLabel } from '../components/CatalogSource';
import { centerInView } from '../components/centerInView';

// Steam's gamepad-scrollable container (scrolls with the right stick). Falls back to a
// plain Focusable if the internal lookup ever fails, so it never crashes.
const ScrollArea = (ScrollPanelGroup ?? Focusable) as FC<any>;

// A full browse page is ~30 items; fewer means we've reached the end.
const PAGE_FULL = 25;
const LEFT_PANEL_WIDTH = 320;

const fmtSubs = (n: number) =>
  n >= 1000 ? `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}k` : `${n}`;
const stripBBCode = (s: string) => s.replace(/\[\/?[^\]]+\]/g, '').trim();

const Row: FC<{
  item: WorkshopCatalogItem; selected: boolean; installed: boolean;
  onSelect: () => void; onActivate: () => void; innerRef?: (el: HTMLDivElement | null) => void;
}> = ({ item, selected, installed, onSelect, onActivate, innerRef }) => (
  // A plain Focusable (like the Installed/Profiles rows) so it gets Steam's focus-ring
  // border — DialogButton doesn't show it. onActivate handles the A press.
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
      {item.preview_url && <img src={item.preview_url} alt="" loading="lazy" style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }} />}
    </div>
    <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
      <div style={{ fontWeight: 600, fontSize: 13, lineHeight: '16px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {item.name}
      </div>
      <div style={{ fontSize: 10, lineHeight: '13px', color: 'var(--gpColorTextSecondary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {fmtSubs(item.subscriptions)} subscribers{installed && ' · installed'}
      </div>
    </div>
  </Focusable>
);

const WorkshopBrowseTab: FC<{ game: GameStatus; onRefresh: () => Promise<void> }> = ({ game, onRefresh }) => {
  const [search, setSearch] = useState('');
  const [debounced, setDebounced] = useState('');
  // Sorted by most-subscribed for now; a press-Y sort selector can re-add the setter.
  const [sort] = useState('subscribed');
  const [items, setItems] = useState<WorkshopCatalogItem[]>([]);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [installing, setInstalling] = useState<string | null>(null);
  const [selectedIndex, setSelectedIndex] = useState(0);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(search.trim()), 350);
    return () => clearTimeout(t);
  }, [search]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true); setSelectedIndex(0);
      try {
        const data = await getWorkshopCatalog(game.appid, debounced, sort, 1);
        if (!cancelled) { setItems(data); setPage(1); setHasMore(data.length >= PAGE_FULL); }
      } catch {
        if (!cancelled) toaster.toast({ title: 'Moddy', body: 'Failed to load Workshop catalog' });
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [game.appid, debounced, sort]);

  const loadMore = async () => {
    if (loadingMore || !hasMore) return;
    setLoadingMore(true);
    try {
      const next = page + 1;
      const data = await getWorkshopCatalog(game.appid, debounced, sort, next);
      const have = new Set(items.map(i => i.id));
      setItems(prev => [...prev, ...data.filter(i => !have.has(i.id))]);
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
    const lastMod = Math.max(0, items.length - 1);
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

  const installedFileIds = useMemo(
    () => new Set(game.installed_mods.map(m => fileIdForMod(game.appid, m.id)).filter(Boolean) as string[]),
    [game.installed_mods, game.appid],
  );
  const isInstalled = (it: WorkshopCatalogItem) => installedFileIds.has(it.id);
  const selected = items[Math.min(selectedIndex, items.length - 1)] ?? null;

  const runInstall = async (it: WorkshopCatalogItem, withDeps = true) => {
    setInstalling(it.id);
    try {
      // Installs the item, plus its declared required items (deps) unless withDeps is false.
      await installWorkshopTree(game.appid, it.id, { name: it.name, thumbnail: it.preview_url, description: it.description }, new Set(), withDeps);
      toaster.toast({ title: 'Moddy', body: `Installing ${it.name}…` });
      await onRefresh();
    } finally { setInstalling(null); }
  };

  const handleInstall = async (it: WorkshopCatalogItem) => {
    // Steam doesn't cascade an item's required items, so installWorkshopTree resolves and
    // subscribes them itself. Surface the not-yet-installed ones first as a confirmation
    // gate (like the Installed tab's enable-deps prompt) before kicking off the install.
    setInstalling(it.id);
    let required: WorkshopCatalogItem[] = [];
    try {
      required = await getWorkshopRequiredItems(game.appid, it.id);
    } catch { /* fall through and install without the prompt */ }
    setInstalling(null);

    const missing = required.filter(r => !installedFileIds.has(r.id));
    if (missing.length > 0) {
      showModal(
        <DependencyInstallModal
          modName={it.name}
          dependencyNames={missing.map(r => r.name)}
          onInstall={close => { close(); runInstall(it, true); }}
          onSkip={close => { close(); runInstall(it, false); }}
        />
      );
      return;
    }
    runInstall(it);
  };

  const handleUninstall = (it: WorkshopCatalogItem) => {
    const modId = workshopModId(game.appid, it.id);
    const dependents = game.installed_mods.filter(m => (m.meta?.dependencies ?? []).includes(modId));
    const run = async (action: 'disable' | 'delete' | 'none') => {
      setInstalling(it.id);
      try {
        if (action === 'delete') for (const d of dependents) await uninstallMod(game.appid, d.id);
        else if (action === 'disable') for (const d of dependents) await toggleMod(game.appid, d.id, false);
        const ok = await uninstallMod(game.appid, modId);
        toaster.toast({ title: 'Moddy', body: ok ? `Removed ${it.name}` : `Failed to remove ${it.name}` });
        await onRefresh();
      } finally { setInstalling(null); }
      const removedIds = action === 'delete'
        ? [modId, ...dependents.map(d => d.id)]
        : [modId];
      showOrphanCleanup({
        game, denylist: new Set<string>(), removedIds, mode: 'uninstall',
        onRefresh, setBusy: b => setInstalling(b ? it.id : null),
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
    <Focusable style={{ display: 'flex', height: '100%', overflow: 'hidden' }}>
      <Focusable style={{ width: LEFT_PANEL_WIDTH, borderRight: '1px solid var(--gpColorSeparator)', display: 'flex', flexDirection: 'column' }}>
        <div style={{ padding: 8 }}>
          <TextField label="Search Workshop" value={search} onChange={e => setSearch(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') e.currentTarget.blur(); }} />
          <CatalogSourceLabel source="workshop" />
          <div style={{ marginTop: 6, minHeight: 16, fontSize: 11, color: 'var(--gpColorTextSecondary)' }}>
            {loading ? 'Loading…' : items.length > 0 ? `${items.length} mod${items.length === 1 ? '' : 's'}` : ''}
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
              {debounced ? 'No matches.' : 'Catalog unavailable — check network.'}
            </div>
          ) : (
            <>
              {items.map((it, i) => (
                <Row key={it.id} item={it} selected={i === selectedIndex} installed={isInstalled(it)}
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
          <div style={{ color: 'var(--gpColorTextSecondary)', padding: 16 }}>Focus an item on the left to see details.</div>
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
                {selected.preview_url && <img src={selected.preview_url} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }} />}
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontWeight: 700, fontSize: 18, lineHeight: '22px' }}>{selected.name}</div>
                <div style={{ fontSize: 12, color: 'var(--gpColorTextSecondary)', marginTop: 2 }}>
                  {fmtSubs(selected.subscriptions)} subscribers
                  {selected.time_updated ? ` · updated ${new Date(selected.time_updated * 1000).toISOString().slice(0, 10)}` : ''}
                </div>
                {selected.tags.length > 0 && (
                  <div style={{ fontSize: 11, color: 'var(--gpColorTextSecondary)', marginTop: 2 }}>{selected.tags.join(' · ')}</div>
                )}
              </div>
            </div>
            <PanelSection>
              <PanelSectionRow>
                <ButtonItem
                  layout="below"
                  disabled={installing === selected.id}
                  onClick={() => (isInstalled(selected) ? handleUninstall(selected) : handleInstall(selected))}
                >
                  {installing === selected.id ? '…' : isInstalled(selected) ? 'Uninstall' : 'Install'}
                </ButtonItem>
              </PanelSectionRow>
            </PanelSection>
            {selected.description && (
              <div style={{ fontSize: 13, lineHeight: '18px', color: 'var(--gpColorTextSecondary)', whiteSpace: 'pre-wrap' }}>
                {stripBBCode(selected.description)}
              </div>
            )}
          </Focusable>
        )}
      </ScrollArea>
    </Focusable>
  );
};

export default WorkshopBrowseTab;
