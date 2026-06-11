import { Tabs, showModal } from '@decky/ui';
import { toaster, addEventListener, removeEventListener } from '@decky/api';
import { useState, useEffect, FC } from 'react';

import { GameStatus, ModUpdate, getSupportedGames, checkModUpdates, saveProfile, getProfiles } from './types';
import ModsTab from './tabs/ModsTab';
import ModLoaderTab from './tabs/ModLoaderTab';
import ProfilesTab from './tabs/ProfilesTab';
import BrowseTab from './tabs/BrowseTab';
import OptionsModal from './components/modals/OptionsModal';
import SaveProfileModal from './components/modals/SaveProfileModal';
import FilterModal, { ModFilter, defaultModFilter } from './components/modals/FilterModal';

const ModPage: FC = () => {
  const appid = parseInt(window.location.pathname.split('/').pop() ?? '0');
  const [game, setGame] = useState<GameStatus | null>(null);
  const [installing, setInstalling] = useState(false);
  const [progress, setProgress] = useState(0);
  const [modloaderReadyOverride, setModloaderReadyOverride] = useState(false);
  const [updates, setUpdates] = useState<ModUpdate[]>([]);
  const [activeTab, setActiveTab] = useState<string>('modloader');
  const [filter, setFilter] = useState<ModFilter>(defaultModFilter);
  const [profilesRefreshKey, setProfilesRefreshKey] = useState(0);
  const [selectionMode, setSelectionMode] = useState(false);

  const refresh = async () => {
    const games = await getSupportedGames();
    const found = games.find(g => g.appid === appid);
    if (found) setGame(found);
  };

  useEffect(() => {
    refresh();
    const listener = addEventListener<[eventAppid: number, percent: number]>(
      'install_progress',
      (eventAppid, percent) => {
        if (eventAppid === appid) setProgress(percent);
      }
    );
    return () => removeEventListener('install_progress', listener);
  }, []);

  // Once modloader is ready, switch to mods tab
  useEffect(() => {
    if (game?.modloader_ready || modloaderReadyOverride) {
      setActiveTab('mods');
    }
  }, [game?.modloader_ready, modloaderReadyOverride]);

  if (!game) return <div style={{ padding: '16px' }}>Game not supported or not installed.</div>;

  const handleCancelInstall = async () => {
    const { cancelInstall } = await import('./types');
    await cancelInstall();
    setInstalling(false);
    setProgress(0);
  };

  const handleFilterMenu = () => {
    showModal(
      <FilterModal filter={filter} onChange={setFilter} />
    );
  };

  const handleSaveProfile = async (close: () => void) => {
    close();
    const existing = await getProfiles(game.appid);
    showModal(
      <SaveProfileModal
        existingNames={existing.map(p => p.name)}
        onSave={async (name, closeSave) => {
          closeSave();
          const ok = await saveProfile(game.appid, name);
          toaster.toast({
            title: 'Moddy',
            body: ok ? `Saved profile "${name}"` : 'Failed to save profile',
          });
          if (ok) setProfilesRefreshKey(k => k + 1);
        }}
      />
    );
  };

  const handleOptionsMenu = () => {
    showModal(
      <OptionsModal
        canSaveProfile={game.installed_mods.length > 0}
        onCheckUpdates={async (close) => {
          close();
          const result = await checkModUpdates(game.appid);
          setUpdates(result);
          if (result.length === 0) {
            toaster.toast({ title: 'Decky Mod Manager', body: 'All mods are up to date' });
          } else {
            toaster.toast({ title: 'Decky Mod Manager', body: `${result.length} update${result.length === 1 ? '' : 's'} available` });
          }
        }}
        onSaveProfile={handleSaveProfile}
        onToggleSelectionMode={activeTab === 'mods' ? (close) => { close(); setSelectionMode(m => !m); } : undefined}
        selectionMode={selectionMode}
      />
    );
  };

  const modloaderReady = game.modloader_ready || modloaderReadyOverride;

  // Build tab list — Mod Loader always first, Mods + Profiles only when ready
  const tabs = [
    {
      id: 'modloader',
      title: 'Mod Loader',
      content: (
        <ModLoaderTab
          game={game}
          onRefresh={refresh}
          onModloaderReady={() => setModloaderReadyOverride(true)}
          setInstalling={setInstalling}
        />
      ),
      footer: {
        onMenuButton: handleOptionsMenu,
        onMenuActionDescription: 'Options',
      },
    },
    ...(modloaderReady ? [{
      id: 'mods',
      title: 'Mods',
      content: (
        <ModsTab
          game={game}
          onRefresh={refresh}
          updates={updates}
          setUpdates={setUpdates}
          installing={installing}
          progress={progress}
          setInstalling={setInstalling}
          setProgress={setProgress}
          onCancel={handleCancelInstall}
          onMenuButton={handleOptionsMenu}
          onFilterButton={handleFilterMenu}
          filter={filter}
          selectionMode={selectionMode}
          setSelectionMode={setSelectionMode}
        />
      ),
      footer: {
        onMenuButton: handleOptionsMenu,
        onMenuActionDescription: 'Options',
        onSecondaryButton: handleFilterMenu,
        onSecondaryActionDescription: 'Filter',
      },
    },
    ...(game.thunderstore_community ? [{
      id: 'browse',
      title: 'Browse',
      content: <BrowseTab game={game} onRefresh={refresh} />,
      footer: {
        onMenuButton: handleOptionsMenu,
        onMenuActionDescription: 'Options',
      },
    }] : []),
    {
      id: 'profiles',
      title: 'Profiles',
      content: (
        <ProfilesTab
          game={game}
          onRefresh={refresh}
          installing={installing}
          progress={progress}
          setInstalling={setInstalling}
          setProgress={setProgress}
          onCancel={handleCancelInstall}
          onMenuButton={handleOptionsMenu}
          refreshKey={profilesRefreshKey}
        />
      ),
      footer: {
        onMenuButton: handleOptionsMenu,
        onMenuActionDescription: 'Options',
      },
    }] : []),
  ];

  return (
    <div style={{
      marginTop: 'var(--basicui-header-height, 40px)',
      height: 'calc(100% - var(--basicui-header-height, 40px))',
    }}>
      <Tabs
        autoFocusContents
        activeTab={activeTab}
        onShowTab={(tab: string) => setActiveTab(tab)}
        tabs={tabs}
      />
    </div>
  );
};

export default ModPage;
