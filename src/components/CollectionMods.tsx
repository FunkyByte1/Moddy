import { Spinner } from '@decky/ui';
import { FC, useState, useEffect } from 'react';

import { CollectionDetail } from '../types';
import { getCollectionDetail } from '../lib/api';

// Lazily fetch + render a collection's mod list (thumbnail + name, optional ones flagged). Shared by
// the Collections browse-tab detail ("what you'd install") and the Installed-tab collection panel
// ("what this collection brought in"). One backend GraphQL call per slug, cached for the mount.
// `onLoaded` hands the fetched detail back up (so a parent can show the description/title too).
const CollectionMods: FC<{
  appid: number;
  slug: string;
  onLoaded?: (detail: CollectionDetail) => void;
}> = ({ appid, slug, onLoaded }) => {
  const [detail, setDetail] = useState<CollectionDetail | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true); setDetail(null);
    getCollectionDetail(appid, slug)
      .then(d => { if (!cancelled) { setDetail(d); onLoaded?.(d); } })
      .catch(() => { if (!cancelled) setDetail(null); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [appid, slug]);

  if (loading) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--gpColorTextSecondary)', fontSize: 12, padding: '8px 0' }}>
        <Spinner style={{ width: 16, height: 16 }} /> Loading mods…
      </div>
    );
  }
  const mods = detail?.mods ?? [];
  if (mods.length === 0) {
    return <div style={{ color: 'var(--gpColorTextSecondary)', fontSize: 12 }}>Couldn’t load this collection’s mods.</div>;
  }

  return (
    <div>
      <div style={{ color: 'var(--gpColorTextSecondary)', fontSize: 12, marginBottom: 6 }}>
        {mods.length} mod{mods.length === 1 ? '' : 's'} in this collection
      </div>
      {mods.map(m => (
        <div key={m.mod_id} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
          <div style={{ width: 28, height: 28, flexShrink: 0, borderRadius: 3, overflow: 'hidden', background: 'rgba(255,255,255,0.08)' }}>
            {m.thumbnail && <img src={m.thumbnail} alt="" loading="lazy" style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }} />}
          </div>
          <span style={{ flex: 1, minWidth: 0, fontSize: 13, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {m.name}
          </span>
          {m.optional && <span style={{ fontSize: 10, color: 'var(--gpColorTextSecondary)', flexShrink: 0 }}>optional</span>}
        </div>
      ))}
    </div>
  );
};

export default CollectionMods;
