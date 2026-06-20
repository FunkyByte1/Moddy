import { ButtonItem, Focusable, PanelSection, PanelSectionRow, ScrollPanelGroup, Spinner, TextField } from '@decky/ui';
import { toaster } from '@decky/api';
import { FC, useState, useEffect, useMemo } from 'react';

import { GameStatus } from '../../types';
import { useQueueFooterProps } from '../../components/DownloadQueueModal';
import { CatalogSourceLabel } from '../../components/CatalogSource';
import { centerInView } from '../../components/centerInView';
import { useGamepadListFocus } from '../../components/useGamepadListFocus';
import { BrowseItem, PagedVenueAdapter } from './types';
import { useBrowseInstall } from './useBrowseInstall';
import { useBrowseUninstall } from './useBrowseUninstall';

// Steam's gamepad-scrollable container (scrolls with the right stick); falls back to a plain
// Focusable if the internal lookup fails. Paged venues load only a few pages, so the list is NOT
// virtualized (unlike the Thunderstore tab) — plain Focusable rows keep gamepad spatial-nav simple.
const ScrollArea = (ScrollPanelGroup ?? Focusable) as FC<any>;
const PAGE_FULL = 25;
const LEFT_PANEL_WIDTH = 320;

const Row: FC<{
  item: BrowseItem; selected: boolean; installed: boolean;
  onSelect: () => void; onActivate: () => void; innerRef?: (el: HTMLDivElement | null) => void;
}> = ({ item, selected, installed, onSelect, onActivate, innerRef }) => (
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
      {item.iconUrl && <img src={item.iconUrl} alt="" loading="lazy" style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }} />}
    </div>
    <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
      <div style={{ fontWeight: 600, fontSize: 13, lineHeight: '16px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {item.title}
      </div>
      <div style={{ fontSize: 10, lineHeight: '13px', color: 'var(--gpColorTextSecondary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {item.subtitle}{installed && ' · installed'}
      </div>
    </div>
  </Focusable>
);

export interface BrowsePagedFilter { installed: boolean; notInstalled: boolean; showNsfw: boolean; }

const BrowsePagedTab: FC<{
  adapter: PagedVenueAdapter;
  game: GameStatus;
  onRefresh: () => Promise<void>;
  filter?: BrowsePagedFilter;   // venues with hasFilter (Nexus)
  onFilterButton?: () => void;
  ready?: boolean;              // default true; Nexus gates the first fetch on the NSFW seed
}> = ({ adapter, game, onRefresh, filter, onFilterButton, ready = true }) => {
  const nsfw = filter?.showNsfw ?? false;

  const [search, setSearch] = useState('');
  const [debounced, setDebounced] = useState('');
  const [items, setItems] = useState<BrowseItem[]>([]);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState(0);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(search.trim()), 350);
    return () => clearTimeout(t);
  }, [search]);

  useEffect(() => {
    if (!ready) return; // Nexus: hold the first fetch until the NSFW seed resolves
    let cancelled = false;
    (async () => {
      setLoading(true); setSelectedIndex(0);
      try {
        const data = await adapter.fetchPage(game, debounced, 1, nsfw);
        if (!cancelled) { setItems(data); setPage(1); setHasMore(data.length >= PAGE_FULL); }
      } catch {
        if (!cancelled) {
          toaster.toast({ title: 'Moddy', body: `Failed to load ${adapter.id === 'nexus' ? 'Nexus' : 'Workshop'} catalog` });
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [adapter, game, debounced, nsfw, ready]);

  const loadMore = async () => {
    if (loadingMore || !hasMore) return;
    setLoadingMore(true);
    try {
      const next = page + 1;
      const data = await adapter.fetchPage(game, debounced, next, nsfw);
      const have = new Set(items.map(i => i.key));
      setItems(prev => [...prev, ...data.filter(i => !have.has(i.key))]);
      setPage(next);
      setHasMore(data.length >= PAGE_FULL);
    } catch {
      toaster.toast({ title: 'Moddy', body: 'Failed to load more' });
    } finally {
      setLoadingMore(false);
    }
  };

  const { detailRef, registerRow, focusRowAfterLoad, focusDetail, focusSelectedRow } =
    useGamepadListFocus({ items, selectedIndex, setSelectedIndex });

  const handleLoadMore = async () => {
    const lastMod = visible.length - 1;
    await loadMore();
    focusRowAfterLoad(lastMod);
  };

  const installedIds = useMemo(() => adapter.installedIds(game), [adapter, game]);
  const isInstalled = (it: BrowseItem) => installedIds.has(it.installId);

  // Nexus filters by installed-status client-side; Workshop has no filter (visible === items).
  const visible = useMemo(() => {
    if (!adapter.hasFilter || !filter) return items;
    return items.filter(it => {
      const inst = installedIds.has(it.installId);
      if (inst && !filter.installed) return false;
      if (!inst && !filter.notInstalled) return false;
      return true;
    });
  }, [adapter, filter, items, installedIds]);

  // Keep the selection in range when the install-status filter shrinks the list.
  useEffect(() => { setSelectedIndex(0); }, [filter?.installed, filter?.notInstalled]);

  const selected = visible[Math.min(selectedIndex, visible.length - 1)] ?? null;

  const { setInstalling, isBusy, addPending, removePending } = useBrowseInstall(adapter.installModel);
  const handleInstall = (it: BrowseItem) =>
    adapter.install(it, { game, onRefresh, setInstalling, addPending, removePending });
  const uninstall = useBrowseUninstall(game, onRefresh, setInstalling);
  const handleUninstall = (it: BrowseItem) => {
    const uid = adapter.uninstallId(game, it);
    uninstall({
      uninstallId: uid, title: it.title, busyKey: it.key,
      // Nexus/Workshop record deps as the full install id — match it directly.
      dependents: game.installed_mods.filter(m => (m.meta?.dependencies ?? []).includes(uid)),
    });
  };

  const detail = selected ? adapter.detail(selected) : null;
  const queueFooter = useQueueFooterProps();

  return (
    <Focusable
      style={{ display: 'flex', height: '100%', overflow: 'hidden' }}
      {...(adapter.installModel === 'queue' ? queueFooter : {})}
      {...(adapter.hasFilter && onFilterButton ? { onSecondaryButton: onFilterButton, onSecondaryActionDescription: 'Filter' } : {})}
    >
      <Focusable style={{ width: LEFT_PANEL_WIDTH, borderRight: '1px solid var(--gpColorSeparator)', display: 'flex', flexDirection: 'column' }}>
        <div style={{ padding: 8 }}>
          <TextField label={adapter.searchLabel} value={search} onChange={e => setSearch(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') e.currentTarget.blur(); }} />
          <CatalogSourceLabel source={adapter.sourceLabel} />
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
              {debounced ? 'No matches.' : adapter.emptyText}
            </div>
          ) : visible.length === 0 ? (
            <div style={{ padding: 16, color: 'var(--gpColorTextSecondary)' }}>
              No mods match the filter.
            </div>
          ) : (
            <>
              {visible.map((it, i) => (
                <Row key={it.key} item={it} selected={i === selectedIndex} installed={isInstalled(it)}
                  onSelect={() => setSelectedIndex(i)} onActivate={focusDetail}
                  innerRef={registerRow(i)} />
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
        {!selected || !detail ? (
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
                {selected.iconUrl && <img src={selected.iconUrl} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }} />}
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontWeight: 700, fontSize: 18, lineHeight: '22px' }}>{selected.title}</div>
                <div style={{ fontSize: 12, color: 'var(--gpColorTextSecondary)', marginTop: 2 }}>{detail.byline}</div>
                {detail.tags.length > 0 && (
                  <div style={{ fontSize: 11, color: 'var(--gpColorTextSecondary)', marginTop: 2 }}>{detail.tags.join(' · ')}</div>
                )}
              </div>
            </div>
            <PanelSection>
              <PanelSectionRow>
                <ButtonItem
                  layout="below"
                  disabled={isBusy(selected.key)}
                  onClick={() => (isInstalled(selected) ? handleUninstall(selected) : handleInstall(selected))}
                >
                  {isBusy(selected.key)
                    ? (isInstalled(selected) ? 'Removing…' : 'Installing…')
                    : isInstalled(selected) ? 'Uninstall' : 'Install'}
                </ButtonItem>
              </PanelSectionRow>
            </PanelSection>
            {detail.description && (
              <div style={{ fontSize: 13, lineHeight: '18px', color: 'var(--gpColorTextSecondary)', whiteSpace: 'pre-wrap' }}>
                {detail.description}
              </div>
            )}
          </Focusable>
        )}
      </ScrollArea>
    </Focusable>
  );
};

export default BrowsePagedTab;
