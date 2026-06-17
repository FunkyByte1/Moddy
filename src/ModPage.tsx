import { Tabs, showModal } from '@decky/ui';
import { toaster, addEventListener, removeEventListener } from '@decky/api';
import { useState, useEffect, useRef, FC } from 'react';

import DownloadQueuePill from './components/DownloadQueuePill';
import { useQueueFooterProps, promptVariant } from './components/DownloadQueueModal';
import { useDownloadQueue } from './downloadQueue';

import { GameStatus, ModUpdate, getGameStatus, checkModUpdates, saveProfile, getProfiles, refreshThunderstoreCatalog, refreshBmiCatalog, resetGame, removeModloaderLaunchOptions, getSetting, NSFW_ENABLED, NSFW_DEFAULT_ON } from './types';
import InstalledTab from './tabs/InstalledTab';
import ModLoaderTab from './tabs/ModLoaderTab';
import ProfilesTab from './tabs/ProfilesTab';
import BrowseTab from './tabs/BrowseTab';
import WorkshopBrowseTab from './tabs/WorkshopBrowseTab';
import NexusBrowseTab from './tabs/NexusBrowseTab';
import OptionsModal from './components/modals/OptionsModal';
import ModLoaderModal from './components/modals/ModLoaderModal';
import ResetGameModal from './components/modals/ResetGameModal';
import SaveProfileModal from './components/modals/SaveProfileModal';
import SaveProfilePickerModal from './components/modals/SaveProfilePickerModal';
import OverwriteProfileModal from './components/modals/OverwriteProfileModal';
import InstalledFilterModal, { InstalledFilter, defaultInstalledFilter } from './components/modals/InstalledFilterModal';
import BrowseFilterModal, { BrowseFilter, defaultBrowseFilter } from './components/modals/BrowseFilterModal';
import NexusFilterModal, { NexusFilter, defaultNexusFilter } from './components/modals/NexusFilterModal';

// Module-level so a parked job's picker auto-pops only once for its whole lifetime, even if the
// page unmounts/remounts (job ids are monotonic, never reused). Prevents duplicate stacked pickers.
const autoPromptedVariants = new Set<number>();

const ModPage: FC = () => {
  const appid = parseInt(window.location.pathname.split('/').pop() ?? '0');
  const [game, setGame] = useState<GameStatus | null>(null);
  const [installing, setInstalling] = useState(false);
  const [progress, setProgress] = useState(0);
  const [modloaderReadyOverride, setModloaderReadyOverride] = useState(false);
  const [updates, setUpdates] = useState<ModUpdate[]>([]);
  const [selectedTab, setSelectedTab] = useState<string | null>(null);
  const [installedFilter, setInstalledFilter] = useState<InstalledFilter>(defaultInstalledFilter);
  const [browseFilter, setBrowseFilter] = useState<BrowseFilter>(defaultBrowseFilter);
  const [nexusFilter, setNexusFilter] = useState<NexusFilter>(defaultNexusFilter);
  // Gates the Nexus tab's first fetch until the NSFW seed below has resolved, so it
  // queries with the right include_adult value once instead of fetching twice.
  const [nsfwSeedResolved, setNsfwSeedResolved] = useState(false);
  const [browseCategories, setBrowseCategories] = useState<string[]>([]);
  const [profilesRefreshKey, setProfilesRefreshKey] = useState(0);
  const [catalogRefreshKey, setCatalogRefreshKey] = useState(0);
  const [selectionMode, setSelectionMode] = useState(false);

  const refresh = async () => {
    const found = await getGameStatus(appid);
    if (found) setGame(found);
  };

  // Background download queue: enqueued installs finish out-of-band, so this page watches the
  // shared store and reacts when one of *its* jobs reaches a terminal state — refreshing the
  // installed list on success and toasting the outcome (the work the old inline install path
  // used to do right after its await).
  const queue = useDownloadQueue();
  const handledJobs = useRef<Set<number>>(new Set());
  useEffect(() => {
    let needRefresh = false;
    for (const j of queue) {
      if (j.appid !== appid) continue;
      // A job parked on a variant choice: pop the picker once. (Re-pickable from the queue modal
      // or the Quick Access panel afterwards.)
      if (j.status === 'needs_input' && !autoPromptedVariants.has(j.job_id)) {
        autoPromptedVariants.add(j.job_id);
        promptVariant(j);
        continue;
      }
      if (handledJobs.current.has(j.job_id)) continue;
      if (j.status === 'done') {
        handledJobs.current.add(j.job_id);
        needRefresh = true;
        toaster.toast({ title: 'Moddy', body: `Installed ${j.name}` });
      } else if (j.status === 'failed') {
        handledJobs.current.add(j.job_id);
        needRefresh = true; // a partial install may have rolled back — resync the list
        const detail = j.error && j.error !== 'Install failed' ? ` — ${j.error}` : '';
        toaster.toast({ title: 'Moddy', body: `Failed to install ${j.name}${detail}` });
      } else if (j.status === 'cancelled') {
        handledJobs.current.add(j.job_id);
        needRefresh = true; // cancel rolls back what it installed — resync the list
      }
    }
    if (needRefresh) refresh();
  }, [queue]);

  // The Downloads (Y) button opens the focus-trapped queue modal, shown as a footer-legend prompt
  // (only while the queue is non-empty). Spread into each tab's footer alongside Options/Filter.
  // The named onOptionsButton (Y) dispatches through SteamUI's footer system reliably regardless
  // of which child holds focus, and shows a bottom-bar prompt — neither of which the View/Select
  // button supports.
  const queueFooter = useQueueFooterProps();

  // Seed the Browse filters' "Show NSFW" from the global default-on sub-setting, once.
  // Only takes effect when NSFW is allowed; the per-session toggle can still override it.
  useEffect(() => {
    (async () => {
      const [enabled, defaultOn] = await Promise.all([
        getSetting(NSFW_ENABLED).catch(() => false),
        getSetting(NSFW_DEFAULT_ON).catch(() => false),
      ]);
      if (enabled && defaultOn) {
        setBrowseFilter(f => ({ ...f, showNsfw: true }));
        setNexusFilter(f => ({ ...f, showNsfw: true }));
      }
      setNsfwSeedResolved(true);
    })();
  }, []);

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

  // Tab selection is derived, never set post-mount: Tabs must mount already on the
  // right tab, because Steam only re-focuses contents on tab changes it initiates
  // itself — a post-mount switch would strand gamepad focus on the previous tab. When
  // the loader isn't ready the only tab is the Mod Loader setup tab; once ready that
  // tab is gone (its controls move to the Options menu) and Installed is the natural
  // first tab. A stale 'modloader' selection — e.g. left over from installing the
  // loader mid-session — falls back to Installed rather than pointing at a removed tab.
  const activeTab = modloaderReady
    ? (selectedTab && selectedTab !== 'modloader' ? selectedTab : 'installed')
    : (selectedTab ?? 'modloader');

  // Latch "ready" for the session once observed. The Mod Loader tab is replaced by a
  // "Manage {loader}" entry in the Options menu once ready, so the management tabs must
  // not vanish if a backend refresh briefly reports not-ready — e.g. disabling
  // MelonLoader hides its ready_indicator (inside the renamed MelonLoader dir). The
  // latch is cleared on uninstall/reset so the setup tab correctly comes back.
  useEffect(() => {
    if (game?.modloader_ready) setModloaderReadyOverride(true);
  }, [game?.modloader_ready]);

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

  const handleInstalledFilterMenu = () => {
    showModal(
      <InstalledFilterModal filter={installedFilter} onChange={setInstalledFilter} />
    );
  };

  const handleBrowseFilterMenu = async () => {
    // Read the gate fresh on open: the routed page can stay mounted across a trip to
    // Settings, so the mount-time value can be stale. Keep state in sync for next time.
    const enabled = !!(await getSetting(NSFW_ENABLED).catch(() => false));
    showModal(
      <BrowseFilterModal
        filter={browseFilter}
        categories={browseCategories}
        defaultFilter={game.catalog_type === 'bmi' ? { ...defaultBrowseFilter, hideLibraries: false } : defaultBrowseFilter}
        nsfwEnabled={enabled}
        onChange={setBrowseFilter}
      />
    );
  };

  const handleNexusFilterMenu = async () => {
    // Read the NSFW gate fresh on open, same as the Thunderstore/BMI filter.
    const enabled = !!(await getSetting(NSFW_ENABLED).catch(() => false));
    // If the gate has since been turned off, drop any lingering NSFW opt-in so adult
    // content stops being fetched (the checkbox to turn it off is hidden when gated off).
    const current = enabled ? nexusFilter : { ...nexusFilter, showNsfw: false };
    if (current.showNsfw !== nexusFilter.showNsfw) setNexusFilter(current);
    showModal(
      <NexusFilterModal filter={current} nsfwEnabled={enabled} onChange={setNexusFilter} />
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

  // Opens the loader-management controls (formerly their own tab) in a modal stacked
  // on top of the Options menu, so its back button returns there. We deliberately keep
  // the Options modal open underneath rather than closing it first.
  const handleManageModloader = (closeOptions: () => void) => {
    showModal(
      <ModLoaderModal
        game={game}
        onRefresh={refresh}
        setInstalling={setInstalling}
        onLoaderRemoved={() => {
          // Uninstall: drop the session "ready" latch and any stale tab selection so the
          // UI falls back to the Mod Loader setup tab (same cleanup as Reset Game), and
          // dismiss the Options modal underneath too — it now names a missing loader.
          setModloaderReadyOverride(false);
          setSelectedTab(null);
          closeOptions();
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
        onToggleSelectionMode={activeTab === 'installed' ? (close) => { close(); setSelectionMode(m => !m); } : undefined}
        selectionMode={selectionMode}
        onRefreshCatalog={(game.catalog_type === 'bmi' || game.catalog_type === 'thunderstore') ? async (close) => {
          close();
          toaster.toast({ title: 'Moddy', body: 'Refreshing mod catalog…' });
          const ok = game.catalog_type === 'bmi'
            ? await refreshBmiCatalog(game.appid)
            : await refreshThunderstoreCatalog(game.appid);
          setCatalogRefreshKey(k => k + 1);
          toaster.toast({ title: 'Moddy', body: ok ? 'Mod catalog refreshed' : 'Failed to refresh catalog' });
        } : undefined}
        onManageModloader={(modloaderReady && game.modloader !== 'steamworkshop') ? handleManageModloader : undefined}
        modloaderName={game.modloader_name}
        onResetGame={handleResetGame}
        canResetGame={game.installed_mods.length > 0 || game.modloader_installed}
      />
    );
  };

  // Build tab list — Mod Loader is a setup-only tab (shown until the loader is ready),
  // then it's replaced by the "Manage {loader}" entry in the Options menu. Mods +
  // Profiles appear once ready.
  const tabs = [
    // Steam Workshop is the platform's own loader (nothing to install), and once the
    // loader is ready its controls live in the Options menu — either way, no tab here.
    ...((game.modloader === 'steamworkshop' || modloaderReady) ? [] : [{
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
        ...queueFooter,
        onMenuButton: handleOptionsMenu,
        onMenuActionDescription: 'Options',
      },
    }]),
    ...(modloaderReady ? [
    // Every game manages its installed mods here; new ones are discovered in Browse
    // (Thunderstore/BMI/Nexus/Workshop, depending on the game).
    {
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
        ...queueFooter,
        onMenuButton: handleOptionsMenu,
        onMenuActionDescription: 'Options',
        onSecondaryButton: handleInstalledFilterMenu,
        onSecondaryActionDescription: 'Filter',
      },
    },
    // Bulk-catalog Browse (Thunderstore/BMI): whole catalog filtered client-side.
    ...(game.catalog_type && game.catalog_type !== 'nexus' ? [{
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
        ...queueFooter,
        onMenuButton: handleOptionsMenu,
        onMenuActionDescription: 'Options',
        onSecondaryButton: handleBrowseFilterMenu,
        onSecondaryActionDescription: 'Filter',
      },
    }] : []),
    // Nexus games browse a server-paginated/searched catalog in their own tab.
    ...(game.catalog_type === 'nexus' ? [{
      id: 'browse',
      title: 'Browse',
      content: (
        <NexusBrowseTab
          game={game}
          onRefresh={refresh}
          filter={nexusFilter}
          onFilterButton={handleNexusFilterMenu}
          ready={nsfwSeedResolved}
        />
      ),
      footer: {
        ...queueFooter,
        onMenuButton: handleOptionsMenu,
        onMenuActionDescription: 'Options',
        onSecondaryButton: handleNexusFilterMenu,
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
        ...queueFooter,
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
          onMenuButton={handleOptionsMenu}
          refreshKey={profilesRefreshKey}
        />
      ),
      footer: {
        ...queueFooter,
        onMenuButton: handleOptionsMenu,
        onMenuActionDescription: 'Options',
      },
    }] : []),
  ];

  return (
    <div style={{
      marginTop: 'var(--basicui-header-height, 40px)',
      height: 'calc(100% - var(--basicui-header-height, 40px))',
      display: 'flex',
      flexDirection: 'column',
    }}>
      {/* Download-queue pill: only present while the queue is non-empty, so it adds no layout
          when idle. Overlaps the tab content (high z-index) when expanded. */}
      {queue.length > 0 && (
        <div style={{ display: 'flex', justifyContent: 'flex-end', padding: '4px 12px', position: 'relative', zIndex: 50 }}>
          <DownloadQueuePill />
        </div>
      )}
      <div style={{ flex: 1, minHeight: 0 }}>
        <Tabs
          autoFocusContents
          activeTab={activeTab}
          onShowTab={(tab: string) => setSelectedTab(tab)}
          tabs={tabs}
        />
      </div>
    </div>
  );
};

export default ModPage;
