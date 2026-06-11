import { DialogButton, Focusable, TextField } from '@decky/ui';
import { toaster } from '@decky/api';
import { FC, useState, useEffect, useMemo } from 'react';

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

const VISIBLE_LIMIT = 100;

const BrowseTab: FC<Props> = ({ game, onRefresh }) => {
  const [catalog, setCatalog] = useState<ThunderstorePackage[]>([]);
  const [denylist, setDenylist] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState('');
  const [installing, setInstalling] = useState<string | null>(null);

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
    let list = catalog.filter(p =>
      !p.is_deprecated &&
      !p.has_nsfw_content &&
      !denylist.has(p.full_name.toLowerCase())
    );
    if (q) {
      list = list.filter(p =>
        p.full_name.toLowerCase().includes(q) ||
        p.latest.description.toLowerCase().includes(q)
      );
    }
    list.sort((a, b) => b.rating_score - a.rating_score);
    return list.slice(0, VISIBLE_LIMIT);
  }, [catalog, query, denylist]);

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

  if (loading) {
    return <div style={{ padding: '16px' }}>Loading catalog...</div>;
  }

  if (catalog.length === 0) {
    return <div style={{ padding: '16px' }}>Catalog unavailable. Check network and try again.</div>;
  }

  return (
    <div style={{ padding: '16px', height: '100%', overflow: 'auto' }}>
      <div style={{ marginBottom: '12px' }}>
        <TextField
          label="Search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>
      <div style={{ marginBottom: '12px', fontSize: '0.85em', color: 'var(--gpColorTextSecondary)' }}>
        Showing {filtered.length} of {catalog.length} mods
        {filtered.length === VISIBLE_LIMIT && ' (cap pending virtualization)'}
      </div>
      <Focusable style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
        {filtered.map(pkg => {
          const isInstalled = installedIds.has(pkg.full_name.toLowerCase());
          const isBusy = installing === pkg.full_name;
          return (
            <div
              key={pkg.full_name}
              style={{
                display: 'flex',
                alignItems: 'center',
                padding: '8px',
                gap: '12px',
                background: 'rgba(255,255,255,0.04)',
                borderRadius: '4px',
              }}
            >
              {pkg.latest.icon && (
                <img
                  src={pkg.latest.icon}
                  alt=""
                  style={{ width: '40px', height: '40px', borderRadius: '4px', flexShrink: 0 }}
                />
              )}
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontWeight: 'bold' }}>{pkg.name}</div>
                <div style={{ fontSize: '0.75em', color: 'var(--gpColorTextSecondary)' }}>
                  by {pkg.owner} · v{pkg.latest.version_number} · {pkg.rating_score} likes
                </div>
                <div
                  style={{
                    fontSize: '0.85em',
                    color: 'var(--gpColorTextSecondary)',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {pkg.latest.description}
                </div>
              </div>
              <DialogButton
                disabled={isInstalled || isBusy}
                onClick={() => handleInstall(pkg)}
                style={{ minWidth: '110px', flexShrink: 0 }}
              >
                {isInstalled ? 'Installed' : isBusy ? 'Installing...' : 'Install'}
              </DialogButton>
            </div>
          );
        })}
      </Focusable>
    </div>
  );
};

export default BrowseTab;
