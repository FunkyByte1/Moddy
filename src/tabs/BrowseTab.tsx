import { ButtonItem, DialogButton, Focusable, PanelSection, PanelSectionRow, TextField } from '@decky/ui';
import { toaster } from '@decky/api';
import { FC, useState, useEffect, useMemo, useRef, CSSProperties } from 'react';
import { FixedSizeList } from 'react-window';

import {
  GameStatus,
  ThunderstorePackage,
  getThunderstoreCatalog,
  installThunderstoreMod,
  getBrowseDenylist,
} from '../types';

interface Props {
  game: GameStatus;
  onRefresh: () => Promise<void>;
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
      onFocusCapture={() => data.onSelect(index)}
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
}> = ({ pkg, installing, isInstalled, onInstall }) => {
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
            by {pkg.owner} · v{pkg.latest.version_number} · {pkg.rating_score} likes
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
            disabled={isInstalled || isBusy}
            onClick={() => onInstall(pkg)}
          >
            {isInstalled ? 'Installed' : isBusy ? 'Installing…' : 'Install'}
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

const BrowseTab: FC<Props> = ({ game, onRefresh }) => {
  const [catalog, setCatalog] = useState<ThunderstorePackage[]>([]);
  const [denylist, setDenylist] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState('');
  const [installing, setInstalling] = useState<string | null>(null);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const listRef = useRef<FixedSizeList | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const [data, deny] = await Promise.all([
          getThunderstoreCatalog(game.appid),
          getBrowseDenylist(),
        ]);
        if (!cancelled) {
          setCatalog(data);
          setDenylist(new Set(deny.map(d => d.toLowerCase())));
        }
      } catch {
        if (!cancelled) {
          toaster.toast({ title: 'Moddy', body: 'Failed to fetch Thunderstore catalog' });
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [game.appid]);

  const installedIds = useMemo(
    () => new Set(game.installed_mods.map(m => m.id.toLowerCase())),
    [game.installed_mods]
  );

  const filtered = useMemo(() => {
    const q = query.toLowerCase().trim();
    let list = catalog.filter(
      p => !p.is_deprecated && !p.has_nsfw_content && !denylist.has(p.full_name.toLowerCase())
    );
    if (q) {
      list = list.filter(
        p =>
          p.full_name.toLowerCase().includes(q) ||
          p.latest.description.toLowerCase().includes(q)
      );
    }
    list.sort((a, b) => b.rating_score - a.rating_score);
    return list;
  }, [catalog, query, denylist]);

  // Reset selection when the filtered list changes (search edits, etc.) so the
  // detail panel never points at a stale index that's now out of bounds.
  useEffect(() => {
    setSelectedIndex(0);
    listRef.current?.scrollToItem(0);
  }, [query]);

  const handleInstall = async (pkg: ThunderstorePackage) => {
    setInstalling(pkg.full_name);
    try {
      const result = await installThunderstoreMod(game.appid, pkg.full_name, null);
      if (result === true) {
        toaster.toast({ title: 'Moddy', body: `Installed ${pkg.name}` });
        await onRefresh();
      } else if (result === false) {
        toaster.toast({ title: 'Moddy', body: `Failed to install ${pkg.name}` });
      }
    } finally {
      setInstalling(null);
    }
  };

  const itemData: RowData = useMemo(
    () => ({ packages: filtered, selectedIndex, installedIds, onSelect: setSelectedIndex }),
    [filtered, selectedIndex, installedIds]
  );

  const selectedPkg = filtered[selectedIndex] ?? null;
  const selectedIsInstalled = selectedPkg
    ? installedIds.has(selectedPkg.full_name.toLowerCase())
    : false;

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
    <Focusable style={{ display: 'flex', height: '100%', overflow: 'hidden' }}>
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
          />
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
          installing={installing}
          isInstalled={selectedIsInstalled}
          onInstall={handleInstall}
        />
      </Focusable>
    </Focusable>
  );
};

export default BrowseTab;
