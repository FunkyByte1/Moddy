import { ButtonItem, Focusable, PanelSection, PanelSectionRow, ScrollPanelGroup, Spinner, TextField, showModal } from '@decky/ui';
import { toaster } from '@decky/api';
import { FC, useState, useEffect, useMemo, useRef } from 'react';

import {
  GameStatus, ThunderstorePackage,
  getNexusCatalog, installNexusMod, uninstallMod, toggleMod,
} from '../types';
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

const NexusBrowseTab: FC<{ game: GameStatus; onRefresh: () => Promise<void> }> = ({ game, onRefresh }) => {
  const [search, setSearch] = useState('');
  const [debounced, setDebounced] = useState('');
  const [items, setItems] = useState<ThunderstorePackage[]>([]);
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
        const data = await getNexusCatalog(game.appid, debounced, 1);
        if (!cancelled) { setItems(data); setPage(1); setHasMore(data.length >= PAGE_FULL); }
      } catch {
        if (!cancelled) toaster.toast({ title: 'Moddy', body: 'Failed to load Nexus catalog' });
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [game.appid, debounced]);

  const loadMore = async () => {
    if (loadingMore || !hasMore) return;
    setLoadingMore(true);
    try {
      const next = page + 1;
      const data = await getNexusCatalog(game.appid, debounced, next);
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

  const installedIds = useMemo(
    () => new Set(game.installed_mods.map(m => m.id.toLowerCase())),
    [game.installed_mods],
  );
  const isInstalled = (it: ThunderstorePackage) => installedIds.has(it.full_name.toLowerCase());
  const selected = items[Math.min(selectedIndex, items.length - 1)] ?? null;

  const handleInstall = async (it: ThunderstorePackage) => {
    setInstalling(it.full_name);
    try {
      const result = await installNexusMod(game.appid, it.full_name, null);
      if (result === 'premium_required') {
        toaster.toast({ title: 'Moddy', body: `${it.name} requires Nexus Premium to download` });
      } else if (result === true) {
        toaster.toast({ title: 'Moddy', body: `Installed ${it.name}` });
        await onRefresh();
      } else if (result === false) {
        toaster.toast({ title: 'Moddy', body: `Failed to install ${it.name}` });
      }
    } finally { setInstalling(null); }
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
    <Focusable style={{ display: 'flex', height: '100%', overflow: 'hidden' }}>
      <Focusable style={{ width: LEFT_PANEL_WIDTH, borderRight: '1px solid var(--gpColorSeparator)', display: 'flex', flexDirection: 'column' }}>
        <div style={{ padding: 8 }}>
          <TextField label="Search Nexus" value={search} onChange={e => setSearch(e.target.value)} />
          <CatalogSourceLabel source="nexus" />
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
              {debounced ? 'No matches.' : 'Catalog unavailable — set your Nexus API key in the Moddy panel and check your network.'}
            </div>
          ) : (
            <>
              {items.map((it, i) => (
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
                  disabled={installing === selected.full_name}
                  onClick={() => (isInstalled(selected) ? handleUninstall(selected) : handleInstall(selected))}
                >
                  {installing === selected.full_name ? '…' : isInstalled(selected) ? 'Uninstall' : 'Install'}
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
