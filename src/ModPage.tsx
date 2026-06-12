import { Tabs, showModal } from '@decky/ui';
import { toaster, addEventListener, removeEventListener } from '@decky/api';
import { useState, useEffect, useRef, FC } from 'react';

import { GameStatus, ModUpdate, getSupportedGames, checkModUpdates, saveProfile, getProfiles } from './types';
import ModsTab from './tabs/ModsTab';
import InstalledTab from './tabs/InstalledTab';
import ModLoaderTab from './tabs/ModLoaderTab';
import ProfilesTab from './tabs/ProfilesTab';
import BrowseTab from './tabs/BrowseTab';
import OptionsModal from './components/modals/OptionsModal';
import SaveProfileModal from './components/modals/SaveProfileModal';
import FilterModal, { ModFilter, defaultModFilter } from './components/modals/FilterModal';
import InstalledFilterModal, { InstalledFilter, defaultInstalledFilter } from './components/modals/InstalledFilterModal';
import BrowseFilterModal, { BrowseFilter, defaultBrowseFilter } from './components/modals/BrowseFilterModal';

const ModPage: FC = () => {
  const appid = parseInt(window.location.pathname.split('/').pop() ?? '0');
  const [game, setGame] = useState<GameStatus | null>(null);
  const [installing, setInstalling] = useState(false);
  const [progress, setProgress] = useState(0);
  const [modloaderReadyOverride, setModloaderReadyOverride] = useState(false);
  const [updates, setUpdates] = useState<ModUpdate[]>([]);
  const [selectedTab, setSelectedTab] = useState<string | null>(null);
  const [filter, setFilter] = useState<ModFilter>(defaultModFilter);
  const [installedFilter, setInstalledFilter] = useState<InstalledFilter>(defaultInstalledFilter);
  const [browseFilter, setBrowseFilter] = useState<BrowseFilter>(defaultBrowseFilter);
  const [browseCategories, setBrowseCategories] = useState<string[]>([]);
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

  const modloaderReady = !!game && (game.modloader_ready || modloaderReadyOverride);

  // Default tab is derived, not set post-mount: Tabs must mount already on the
  // right tab. Mounting on 'modloader' and switching to 'mods' a frame later
  // strands gamepad focus in the hidden Mod Loader content — Steam only
  // re-focuses contents on tab changes it initiates itself, so the next R1
  // press routes input back to the stale tab.
  const defaultManageTab = game?.thunderstore_community ? 'installed' : 'mods';
  const activeTab = selectedTab ?? (modloaderReady ? defaultManageTab : 'modloader');

  // Still jump to Mods when the modloader becomes ready mid-session (e.g.
  // right after installing it from the Mod Loader tab).
  const prevReadyRef = useRef(modloaderReady);
  useEffect(() => {
    if (modloaderReady && !prevReadyRef.current) setSelectedTab(defaultManageTab);
    prevReadyRef.current = modloaderReady;
  }, [modloaderReady]);

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

  const handleInstalledFilterMenu = () => {
    showModal(
      <InstalledFilterModal filter={installedFilter} onChange={setInstalledFilter} />
    );
  };

  const handleBrowseFilterMenu = () => {
    showModal(
      <BrowseFilterModal
        filter={browseFilter}
        categories={browseCategories}
        onChange={setBrowseFilter}
      />
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
        onToggleSelectionMode={activeTab === 'mods' || activeTab === 'installed' ? (close) => { close(); setSelectionMode(m => !m); } : undefined}
        selectionMode={selectionMode}
      />
    );
  };

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
    ...(modloaderReady ? [
    // Thunderstore games manage installed mods here and discover new ones in
    // Browse; non-Thunderstore games keep the curated Mods tab as their only
    // install path.
    game.thunderstore_community ? {
      id: 'installed',
      title: 'Installed',
      content: (
        <InstalledTab
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
          onFilterButton={handleInstalledFilterMenu}
          filter={installedFilter}
          selectionMode={selectionMode}
          setSelectionMode={setSelectionMode}
        />
      ),
      footer: {
        onMenuButton: handleOptionsMenu,
        onMenuActionDescription: 'Options',
        onSecondaryButton: handleInstalledFilterMenu,
        onSecondaryActionDescription: 'Filter',
      },
    } : {
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
      content: (
        <BrowseTab
          game={game}
          onRefresh={refresh}
          filter={browseFilter}
          onFilterButton={handleBrowseFilterMenu}
          onCategoriesChange={setBrowseCategories}
        />
      ),
      footer: {
        onMenuButton: handleOptionsMenu,
        onMenuActionDescription: 'Options',
        onSecondaryButton: handleBrowseFilterMenu,
        onSecondaryActionDescription: 'Filter',
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
        onShowTab={(tab: string) => setSelectedTab(tab)}
        tabs={tabs}
      />
    </div>
  );
};

export default ModPage;
