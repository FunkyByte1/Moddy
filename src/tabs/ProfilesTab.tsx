import { ButtonItem, Focusable, PanelSection, PanelSectionRow, showModal } from '@decky/ui';
import { toaster } from '@decky/api';
import { useState, useEffect, FC } from 'react';

import {
  GameStatus, Profile, ProfileMod,
  getProfiles, renameProfile, deleteProfile,
  installMod, toggleMod,
} from '../types';
import ApplyProfileModal from '../components/modals/ApplyProfileModal';
import RenameProfileModal from '../components/modals/RenameProfileModal';
import DeleteProfileModal from '../components/modals/DeleteProfileModal';

const formatDate = (iso: string): string => {
  try {
    const d = new Date(iso);
    return d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  } catch {
    return iso;
  }
};

const ProfilesTab: FC<{
  game: GameStatus;
  onRefresh: () => Promise<void>;
  installing: boolean;
  progress: number;
  setInstalling: (v: boolean) => void;
  setProgress: (v: number) => void;
  onCancel: () => void;
  onMenuButton: () => void;
  refreshKey: number;
}> = ({ game, onRefresh, installing, progress, setInstalling, setProgress, onCancel, onMenuButton, refreshKey }) => {
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [busy, setBusy] = useState(false);

  const loadProfiles = async () => {
    const list = await getProfiles(game.appid);
    setProfiles(list);
  };

  useEffect(() => { loadProfiles(); }, [refreshKey]);

  const selected = profiles[Math.min(selectedIndex, profiles.length - 1)];

  const modNameFor = (id: string): string =>
    game.mods.find(m => m.id === id)?.name
    ?? game.installed_mods.find(m => m.id === id)?.filename.replace('.dll', '')
    ?? id;

  const handleApply = (profile: Profile) => {
    const installedById = new Map(game.installed_mods.map(m => [m.id, m]));
    const profileById = new Map(profile.mods.map(m => [m.id, m]));

    const missing: ProfileMod[] = [];
    const versionChange: ProfileMod[] = [];
    for (const pm of profile.mods) {
      const im = installedById.get(pm.id);
      if (!im) {
        missing.push(pm);
      } else if (pm.version && im.version && pm.version !== im.version) {
        versionChange.push(pm);
      }
    }

    const applyChanges = async (installMissing: boolean) => {
      setBusy(true);
      const toInstall = [
        ...(installMissing ? missing : []),
        ...versionChange,
      ];

      // Track what will end up installed + enabled after the install pass.
      // Freshly installed mods land enabled.
      const enabledAfterInstall = new Map<string, boolean>(
        game.installed_mods.map(m => [m.id, m.enabled])
      );

      for (const pm of toInstall) {
        const modDef = game.mods.find(m => m.id === pm.id);
        if (!modDef) continue;
        setInstalling(true); setProgress(0);
        const ok = await installMod(game.appid, pm.id, pm.version);
        setInstalling(false);
        if (ok === null) {
          await onRefresh();
          setBusy(false);
          return;
        }
        if (ok) {
          enabledAfterInstall.set(pm.id, true);
        } else {
          toaster.toast({ title: 'Moddy', body: `Failed to install ${modDef.name}` });
        }
      }

      // Toggle phase: bring every mod to its target enabled state.
      let toggleCount = 0;
      for (const pm of profile.mods) {
        if (!enabledAfterInstall.has(pm.id)) continue; // skipped missing
        if (enabledAfterInstall.get(pm.id) !== pm.enabled) {
          await toggleMod(game.appid, pm.id, pm.enabled);
          toggleCount++;
        }
      }
      for (const im of game.installed_mods) {
        if (!profileById.has(im.id) && im.enabled) {
          await toggleMod(game.appid, im.id, false);
          toggleCount++;
        }
      }

      await onRefresh();
      setBusy(false);
      toaster.toast({
        title: 'Moddy',
        body: `Applied "${profile.name}"`
          + (toInstall.length ? `, ${toInstall.length} installed` : '')
          + (toggleCount ? `, ${toggleCount} toggled` : ''),
      });
    };

    if (missing.length > 0 || versionChange.length > 0) {
      showModal(
        <ApplyProfileModal
          profileName={profile.name}
          missingNames={missing.map(m => modNameFor(m.id))}
          versionChanges={versionChange.map(m => ({
            name: modNameFor(m.id),
            from: installedById.get(m.id)?.version ?? null,
            to: m.version,
          }))}
          onInstallAndApply={(close) => { close(); applyChanges(true); }}
          onSkipAndApply={(close) => { close(); applyChanges(false); }}
        />
      );
    } else {
      applyChanges(false);
    }
  };

  const handleRename = (profile: Profile) => {
    showModal(
      <RenameProfileModal
        currentName={profile.name}
        existingNames={profiles.map(p => p.name)}
        onRename={async (newName, close) => {
          close();
          setBusy(true);
          const ok = await renameProfile(game.appid, profile.name, newName);
          if (!ok) toaster.toast({ title: 'Moddy', body: 'Failed to rename profile' });
          await loadProfiles();
          setBusy(false);
        }}
      />
    );
  };

  const handleDelete = (profile: Profile) => {
    showModal(
      <DeleteProfileModal
        profileName={profile.name}
        onDelete={async (close) => {
          close();
          setBusy(true);
          const ok = await deleteProfile(game.appid, profile.name);
          if (!ok) toaster.toast({ title: 'Moddy', body: 'Failed to delete profile' });
          await loadProfiles();
          setBusy(false);
        }}
      />
    );
  };

  return (
    <Focusable style={{ display: 'flex', height: '100%', overflow: 'hidden' }}>
      <Focusable
        style={{ width: '30%', overflowY: 'auto', paddingBottom: '60px', borderRight: '1px solid var(--gpColorSeparator)', padding: '8px' }}
        onMenuButton={onMenuButton}
        onMenuActionDescription="Options"
      >
        {profiles.length === 0 ? (
          <div style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.85em', padding: '8px' }}>
            No profiles saved yet. Use Options → Save Current Mods as Profile to create one.
          </div>
        ) : profiles.map((p, i) => {
          const enabledCount = p.mods.filter(m => m.enabled).length;
          return (
            <Focusable
              key={p.name}
              onFocus={() => setSelectedIndex(i)}
              onActivate={() => handleApply(p)}
              style={{
                padding: '10px 8px', borderRadius: '4px', marginBottom: '2px',
                background: i === selectedIndex ? 'var(--gpColorHighlight1)' : 'transparent',
                cursor: 'pointer', outline: 'none',
              }}
            >
              <div style={{ fontWeight: i === selectedIndex ? 'bold' : 'normal', fontSize: '0.9em', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {p.name}
              </div>
              <div style={{ fontSize: '0.75em', color: 'var(--gpColorTextSecondary)' }}>
                {p.mods.length} mod{p.mods.length === 1 ? '' : 's'} · {enabledCount} enabled
              </div>
            </Focusable>
          );
        })}
      </Focusable>

      {selected && (
        <Focusable
          style={{ flex: 1, overflowY: 'auto', padding: '12px 16px', paddingBottom: '60px', display: 'flex', flexDirection: 'column' }}
          onMenuButton={onMenuButton}
          onMenuActionDescription="Options"
        >
          {installing && (
            <div style={{ marginBottom: '12px' }}>
              <div style={{ marginBottom: '4px', fontSize: '0.85em', color: 'var(--gpColorTextSecondary)' }}>
                {`Installing... ${progress}%`}
              </div>
              <div style={{ width: '100%', height: '6px', background: 'var(--gpColorBgTertiary)', borderRadius: '3px', marginBottom: '6px' }}>
                <div style={{ width: `${progress}%`, height: '100%', background: 'var(--gpSystemLightBlue)', borderRadius: '3px', transition: 'width 0.2s ease' }} />
              </div>
              <ButtonItem layout="below" onClick={onCancel}>Cancel</ButtonItem>
            </div>
          )}

          <div style={{ fontWeight: 'bold', fontSize: '1.1em', marginBottom: '4px' }}>{selected.name}</div>
          <div style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.85em', marginBottom: '12px' }}>
            Saved {formatDate(selected.created_at)} · {selected.mods.length} mod{selected.mods.length === 1 ? '' : 's'}
          </div>

          <div style={{ fontSize: '0.85em', marginBottom: '12px' }}>
            <div style={{ color: 'var(--gpColorTextSecondary)', marginBottom: '4px' }}>Mods:</div>
            {selected.mods.length === 0 ? (
              <div style={{ color: 'var(--gpColorTextSecondary)', fontStyle: 'italic' }}>(empty profile)</div>
            ) : selected.mods.map(m => (
              <div key={m.id} style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '2px' }}>
                <span style={{ color: m.enabled ? '#5ba85b' : 'var(--gpColorTextSecondary)' }}>
                  {m.enabled ? '✓' : '○'}
                </span>
                <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {modNameFor(m.id)}
                </span>
                {m.version && (
                  <span style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.9em' }}>{m.version}</span>
                )}
              </div>
            ))}
          </div>

          <PanelSection>
            <PanelSectionRow>
              <ButtonItem layout="below" onClick={() => handleApply(selected)} disabled={busy || installing}>
                Apply Profile
              </ButtonItem>
            </PanelSectionRow>
            <PanelSectionRow>
              <ButtonItem layout="below" onClick={() => handleRename(selected)} disabled={busy || installing}>
                Rename
              </ButtonItem>
            </PanelSectionRow>
            <PanelSectionRow>
              <ButtonItem layout="below" onClick={() => handleDelete(selected)} disabled={busy || installing}>
                Delete
              </ButtonItem>
            </PanelSectionRow>
          </PanelSection>
        </Focusable>
      )}
    </Focusable>
  );
};

export default ProfilesTab;
