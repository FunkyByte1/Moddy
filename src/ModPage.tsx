import { Tabs, showModal } from '@decky/ui';
import { toaster, addEventListener, removeEventListener } from '@decky/api';
import { useState, useEffect, useRef, FC } from 'react';

import { GameStatus, ModUpdate, getSupportedGames, checkModUpdates, saveProfile, getProfiles, refreshThunderstoreCatalog, refreshBmiCatalog, resetGame, removeModloaderLaunchOptions } from './types';
import ModsTab from './tabs/ModsTab';
import InstalledTab from './tabs/InstalledTab';
import ModLoaderTab from './tabs/ModLoaderTab';
import ProfilesTab from './tabs/ProfilesTab';
import BrowseTab from './tabs/BrowseTab';
import WorkshopBrowseTab from './tabs/WorkshopBrowseTab';
import OptionsModal from './components/modals/OptionsModal';
import ResetGameModal from './components/modals/ResetGameModal';
import SaveProfileModal from './components/modals/SaveProfileModal';
import SaveProfilePickerModal from './components/modals/SaveProfilePickerModal';
import OverwriteProfileModal from './components/modals/OverwriteProfileModal';
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
  const [catalogRefreshKey, setCatalogRefreshKey] = useState(0);
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
  const defaultManageTab = game?.catalog_type ? 'installed' : 'mods';
  const activeTab = selectedTab ?? (modloaderReady ? defaultManageTab : 'modloader');

  // Still jump to Mods when the modloader becomes ready mid-session (e.g.
  // right after installing it from the Mod Loader tab).
  const prevReadyRef = useRef(modloaderReady);
  useEffect(() => {
    if (modloaderReady && !prevReadyRef.current) setSelectedTab(defaultManageTab);
    prevReadyRef.current = modloaderReady;
  }, [modloaderReady]);

  // Libraries are hidden by default everywhere except BMI: BMI exposes its libraries
  // ("API" mods) for direct install, so hiding them would be surprising, whereas
  // Thunderstore libraries are auto-installed dependencies worth decluttering. Flip the
  // library defaults to "show" once, on first load, for BMI-backed games.
  const libDefaultsApplied = useRef(false);
  useEffect(() => {
    if (!game || libDefaultsApplied.current) return;
    libDefaultsApplied.current = true;
    if (game.catalog_type === 'bmi') {
      setBrowseFilter(f => ({ ...f, hideLibraries: false }));
      setInstalledFilter(f => ({ ...f, hideLibraries: false }));
    }
  }, [game]);

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
        defaultFilter={game.catalog_type === 'bmi' ? { ...defaultBrowseFilter, hideLibraries: false } : defaultBrowseFilter}
        onChange={setBrowseFilter}
      />
    );
  };

  const persistProfile = async (name: string) => {
    const ok = await saveProfile(game.appid, name);
    toaster.toast({
      title: 'Moddy',
      body: ok ? `Saved profile "${name}"` : 'Failed to save profile',
    });
    if (ok) setProfilesRefreshKey(k => k + 1);
  };

  const openNameEntry = (existingNames: string[]) => {
    showModal(
      <SaveProfileModal
        existingNames={existingNames}
        onSave={async (name, closeSave) => {
          closeSave();
          await persistProfile(name);
        }}
      />
    );
  };

  const handleSaveProfile = async (close: () => void) => {
    close();
    const existingNames = (await getProfiles(game.appid)).map(p => p.name);
    // Nothing to overwrite yet — skip the picker and go straight to naming.
    if (existingNames.length === 0) {
      openNameEntry(existingNames);
      return;
    }
    showModal(
      <SaveProfilePickerModal
        existingNames={existingNames}
        onNewProfile={(closePicker) => {
          closePicker();
          openNameEntry(existingNames);
        }}
        onOverwrite={(name, closePicker) => {
          closePicker();
          showModal(
            <OverwriteProfileModal
              profileName={name}
              onConfirm={async (closeConfirm) => {
                closeConfirm();
                await persistProfile(name);
              }}
            />
          );
        }}
      />
    );
  };

  const handleResetGame = (close: () => void) => {
    close();
    showModal(
      <ResetGameModal
        gameName={game.name}
        onConfirm={async (closeModal) => {
          closeModal();
          toaster.toast({ title: 'Moddy', body: `Resetting ${game.name}…` });
          const result = await resetGame(game.appid);
          if (result.ok || result.mods_removed > 0 || result.modloader_removed) {
            removeModloaderLaunchOptions(game.appid, game.modloader_launch_options);
            setUpdates([]);
            setSelectionMode(false);
            // The modloader is gone now; drop the session "ready" override and any
            // stale tab selection so the UI falls back to the Mod Loader tab instead
            // of leaving the mod-management tabs mounted with no loader behind them.
            setModloaderReadyOverride(false);
            setSelectedTab(null);
          }
          await refresh();
          toaster.toast({
            title: 'Moddy',
            body: result.ok
              ? `${game.name} reset to its original state`
              : 'Reset finished with some errors — check the log',
          });
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
        onRefreshCatalog={game.catalog_type ? async (close) => {
          close();
          toaster.toast({ title: 'Moddy', body: 'Refreshing mod catalog…' });
          const ok = game.catalog_type === 'bmi'
            ? await refreshBmiCatalog(game.appid)
            : await refreshThunderstoreCatalog(game.appid);
          setCatalogRefreshKey(k => k + 1);
          toaster.toast({ title: 'Moddy', body: ok ? 'Mod catalog refreshed' : 'Failed to refresh catalog' });
        } : undefined}
        onResetGame={handleResetGame}
        canResetGame={game.installed_mods.length > 0 || game.modloader_installed}
      />
    );
  };

  // Build tab list — Mod Loader always first, Mods + Profiles only when ready
  const tabs = [
    // Steam Workshop is the platform's own loader — there's nothing to install, so
    // these games skip the Mod Loader tab entirely.
    ...(game.modloader === 'steamworkshop' ? [] : [{
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
    }]),
    ...(modloaderReady ? [
    // Catalog-backed games (Thunderstore or BMI) manage installed mods here and
    // discover new ones in Browse; curated-only games keep the Mods tab as their
    // only install path.
    game.catalog_type ? {
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
      title: game.modloader === 'steamworkshop' ? 'Installed' : 'Mods',
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
    ...(game.catalog_type ? [{
      id: 'browse',
      title: 'Browse',
      content: (
        <BrowseTab
          game={game}
          onRefresh={refresh}
          filter={browseFilter}
          onFilterButton={handleBrowseFilterMenu}
          onCategoriesChange={setBrowseCategories}
          refreshKey={catalogRefreshKey}
        />
      ),
      footer: {
        onMenuButton: handleOptionsMenu,
        onMenuActionDescription: 'Options',
        onSecondaryButton: handleBrowseFilterMenu,
        onSecondaryActionDescription: 'Filter',
      },
    }] : []),
    // Steam Workshop games browse a server-paginated catalog in their own tab.
    ...(game.modloader === 'steamworkshop' ? [{
      id: 'browse',
      title: 'Browse',
      content: (
        <WorkshopBrowseTab game={game} onRefresh={refresh} />
      ),
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
        onShowTab={(tab: string) => setSelectedTab(tab)}
        tabs={tabs}
      />
    </div>
  );
};

export default ModPage;
