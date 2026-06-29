import { Tabs, showModal, DialogButton, Spinner } from '@decky/ui';
import { toaster, addEventListener, removeEventListener } from '@decky/api';
import { useState, useEffect, useRef, FC } from 'react';

import DownloadQueuePill from '../components/DownloadQueuePill';
import { useQueueFooterProps, promptVariant } from '../components/DownloadQueueModal';
import { useDownloadQueue } from '../lib/downloadQueue';

import { GameStatus, ModUpdate } from '../types';
import { getGameStatus, checkModUpdates, saveProfile, getProfiles, refreshThunderstoreCatalog, refreshBmiCatalog, resetGame, removeModloaderLaunchOptions, setGameToProton, applyVanillaMode, getSetting, gameHasCollections, NSFW_ENABLED, NSFW_DEFAULT_ON } from '../lib/api';
import InstalledTab from '../tabs/InstalledTab';
import ModLoaderTab from '../tabs/ModLoaderTab';
import ProfilesTab from '../tabs/ProfilesTab';
import BrowsePagedTab from '../tabs/browse/BrowsePagedTab';
import { nexusAdapter } from '../tabs/browse/nexusAdapter';
import { workshopAdapter } from '../tabs/browse/workshopAdapter';
import { thunderstoreAdapter, bmiAdapter } from '../tabs/browse/catalogAdapter';
import { ficsitAdapter } from '../tabs/browse/ficsitAdapter';
import { collectionsAdapterFor, venueHasCollections, COLLECTIONS_HINT } from '../tabs/browse/collectionVenues';
import { installedCollections } from '../lib/modSources';
import OptionsModal from '../components/modals/OptionsModal';
import VanillaView from '../components/VanillaView';
import ModLoaderModal from '../components/modals/ModLoaderModal';
import ResetGameModal from '../components/modals/ResetGameModal';
import SaveProfileModal from '../components/modals/SaveProfileModal';
import SaveProfilePickerModal from '../components/modals/SaveProfilePickerModal';
import OverwriteProfileModal from '../components/modals/OverwriteProfileModal';
import InstalledFilterModal, { InstalledFilter, defaultInstalledFilter } from '../components/modals/InstalledFilterModal';
import BrowseFilterModal, { BrowseFilter, defaultBrowseFilter } from '../components/modals/BrowseFilterModal';
import NexusFilterModal, { NexusFilter, defaultNexusFilter } from '../components/modals/NexusFilterModal';

// Module-level so a parked job's picker auto-pops only once for its whole lifetime, even if the
// page unmounts/remounts (job ids are monotonic, never reused). Prevents duplicate stacked pickers.
const autoPromptedVariants = new Set<number>();

// Likewise module-level: a job's outcome toast fires once per job, ever. Finished jobs linger in
// the shared queue until cleared, so a mount-local set would re-toast every "Installed …" each
// time Configure Mods is reopened. Job ids are monotonic and never reused.
const handledJobs = new Set<number>();

// Whether a game's Nexus venue actually has any collections is a runtime fact (the live catalog), so
// the Collections tab is gated on a one-shot probe rather than shown for every Nexus game and left
// empty (e.g. Slime Rancher 2 has none). The probe ignores the NSFW setting — tab presence reflects
// "this game has collections" (so RE4, which has both NSFW and non-NSFW ones, always shows it); the
// list inside still filters adult content per the setting. A hardcoded per-game hint (COLLECTIONS_HINT)
// seeds the first paint so the tab doesn't pop in; the probe result (cached per session) overrides it.
const _collectionsProbedCache = new Map<number, boolean>();

const ModPage: FC = () => {
  const appid = parseInt(window.location.pathname.split('/').pop() ?? '0');
  const [game, setGame] = useState<GameStatus | null>(null);
  // Distinguishes "still loading the first status" from "loaded, but no game" — without it the
  // null-game branch can't tell a pending fetch from a genuinely unsupported game, so it showed
  // the "not supported" text during load.
  const [loaded, setLoaded] = useState(false);
  const [installing, setInstalling] = useState(false);
  const [progress, setProgress] = useState(0);
  const [modloaderReadyOverride, setModloaderReadyOverride] = useState(false);
  const [updates, setUpdates] = useState<ModUpdate[]>([]);
  const [selectedTab, setSelectedTab] = useState<string | null>(null);
  // null = not yet probed (fall back to the hardcoded hint); true/false = live probe result.
  const [collectionsProbed, setCollectionsProbed] = useState<boolean | null>(_collectionsProbedCache.get(appid) ?? null);
  const [installedFilter, setInstalledFilter] = useState<InstalledFilter>(defaultInstalledFilter);
  const [browseFilter, setBrowseFilter] = useState<BrowseFilter>(defaultBrowseFilter);
  const [nexusFilter, setNexusFilter] = useState<NexusFilter>(defaultNexusFilter);
  // Lifted so it survives the Nexus Browse tab's remount when a server-side filter (Show NSFW / sort)
  // changes — see the key on that tab below.
  const [nexusSearch, setNexusSearch] = useState('');
  // Gates the Nexus tab's first fetch until the NSFW seed below has resolved, so it
  // queries with the right include_adult value once instead of fetching twice.
  const [nsfwSeedResolved, setNsfwSeedResolved] = useState(false);
  const [browseCategories, setBrowseCategories] = useState<string[]>([]);
  const [profilesRefreshKey, setProfilesRefreshKey] = useState(0);
  const [catalogRefreshKey, setCatalogRefreshKey] = useState(0);
  const [selectionMode, setSelectionMode] = useState(false);
  // Optimistically hide the "force Proton" banner the moment the user applies it — config.vdf may
  // not have flushed by the time refresh() re-reads it, so don't wait on the backend round-trip.
  const [protonApplied, setProtonApplied] = useState(false);
  const [settingProton, setSettingProton] = useState(false);
  // Whole-page work (vanilla toggle, reset) shows a content-area spinner with this label and
  // gates input by replacing the tabs/buttons — null when idle.
  const [busyLabel, setBusyLabel] = useState<string | null>(null);

  const refresh = async () => {
    // Always reach setLoaded(true), even if the status call rejects — otherwise the page hangs
    // forever on the "Loading…" spinner instead of falling through to a usable state.
    try {
      const found = await getGameStatus(appid);
      if (found) setGame(found);
    } catch (e) {
      console.error('[Moddy] getGameStatus failed', e);
    } finally {
      setLoaded(true);
    }
  };

  // Background download queue: enqueued installs finish out-of-band, so this page watches the
  // shared store and reacts when one of *its* jobs reaches a terminal state — refreshing the
  // installed list on success and toasting the outcome (the work the old inline install path
  // used to do right after its await).
  const queue = useDownloadQueue();
  useEffect(() => {
    let needRefresh = false;
    for (const j of queue) {
      if (j.appid !== appid) continue;
      // A job parked on a variant choice: pop the picker once (re-pickable from the queue modal /
      // QAM afterwards), and refresh so any dependencies installed on the first pass show now.
      if (j.status === 'needs_input' && !autoPromptedVariants.has(j.job_id)) {
        autoPromptedVariants.add(j.job_id);
        promptVariant(j);
        refresh();
        continue;
      }
      if (handledJobs.has(j.job_id)) continue;
      if (j.status === 'done') {
        handledJobs.add(j.job_id);
        needRefresh = true;
        toaster.toast({ title: 'Moddy', body: `Installed ${j.name}${j.warning ? ` — ${j.warning}` : ''}` });
      } else if (j.status === 'failed') {
        handledJobs.add(j.job_id);
        needRefresh = true; // a partial install may have rolled back — resync the list
        const detail = j.error && j.error !== 'Install failed' ? ` — ${j.error}` : '';
        toaster.toast({ title: 'Moddy', body: `Failed to install ${j.name}${detail}` });
      } else if (j.status === 'cancelled') {
        handledJobs.add(j.job_id);
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
  const queueFooter = useQueueFooterProps(appid);

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

  // Probe whether this game's venue actually has collections, to confirm/correct the hardcoded hint
  // (the tab shows from the hint on first paint; the probe overrides it if reality differs or no hint
  // exists). The probe ignores NSFW; the list inside still filters adult content per the setting.
  useEffect(() => {
    if (!game || !venueHasCollections(game)) return;
    const cached = _collectionsProbedCache.get(appid);
    if (cached !== undefined) { setCollectionsProbed(cached); return; }
    let cancelled = false;
    gameHasCollections(appid)
      .then(has => { if (!cancelled) { _collectionsProbedCache.set(appid, has); setCollectionsProbed(has); } })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [appid, game?.catalog_type]);

  useEffect(() => {
    refresh();
    const listener = addEventListener<[eventAppid: number, percent: number]>(
      'install_progress',
      (eventAppid, percent) => {
        if (eventAppid === appid) setProgress(percent);
      }
    );
    // The backend warms an uncached Browse catalog out-of-band (so the first status returns
    // instantly); it emits this once the catalog lands so we re-pull and library mods get
    // classified/hidden. Without it the page would paint, but with libraries showing until the
    // next manual refresh.
    const staleListener = addEventListener<[eventAppid: number]>(
      'game_status_stale',
      (eventAppid) => { if (eventAppid === appid) refresh(); }
    );
    return () => {
      removeEventListener('install_progress', listener);
      removeEventListener('game_status_stale', staleListener);
    };
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

  if (!game) {
    // Loading vs. genuinely-null are different states now: show a spinner until the first status
    // resolves, only then fall back to the unsupported message.
    if (!loaded) {
      return (
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '12px', height: '100%', minHeight: '160px' }}>
          <Spinner style={{ width: 32, height: 32 }} />
          <span style={{ color: 'var(--gpColorTextSecondary)' }}>Loading…</span>
        </div>
      );
    }
    return (
      <div style={{ padding: '24px', color: 'var(--gpColorTextSecondary)', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: '8px', textAlign: 'center', height: '100%' }}>
        <span style={{ fontSize: '2.8em', opacity: 0.55, lineHeight: 1 }}>⊘</span>
        <span>Game not supported or not installed.</span>
      </div>
    );
  }

  const handleCancelInstall = async () => {
    const { cancelInstall } = await import('../lib/api');
    await cancelInstall();
    setInstalling(false);
    setProgress(0);
  };

  const handleInstalledFilterMenu = () => {
    showModal(
      <InstalledFilterModal
        filter={installedFilter}
        onChange={setInstalledFilter}
        collections={installedCollections(game.installed_mods)}
      />
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

  // ficsit reuses the server-paged sort/status filter (shared state with Nexus — a game is one or
  // the other), minus the NSFW + library sections it has no concept of.
  const handleFicsitFilterMenu = () => {
    showModal(
      <NexusFilterModal filter={nexusFilter} onChange={setNexusFilter} hideNsfwSection hideLibrariesSection />
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
          if (busyLabel) return;  // a vanilla toggle / reset is already running — don't double-fire
          // Spinner replaces the page while resetting (can take several seconds — many uninstalls);
          // single completion toast, no leading "Resetting…" toast queued ahead of it. The finally
          // clears the spinner even if the reset or refresh throws (otherwise the page is stranded).
          setBusyLabel(`Resetting ${game.name}…`);
          let result: Awaited<ReturnType<typeof resetGame>> | null = null;
          try {
            result = await resetGame(game.appid);
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
          } catch (e) {
            console.error('[Moddy] reset failed', e);
          } finally {
            setBusyLabel(null);
          }
          toaster.toast({
            title: 'Moddy',
            body: result?.ok
              ? `${game.name} reset to its original state`
              : 'Reset finished with some errors — check the log',
          });
        }}
      />
    );
  };

  // Toggle the whole game between modded and vanilla (play-unmodded). Reversible and
  // non-destructive — nothing is deleted, so no confirm modal; a toast + refresh is enough.
  const handleToggleVanilla = async (close: () => void) => {
    close();
    if (busyLabel) return;
    const goVanilla = !game.vanilla;
    // Spinner replaces the page for the duration; a single toast fires on completion (a second,
    // queued toast would just sit ~5s behind a leading one, looking like the work hung). The
    // finally is essential: if the op or refresh throws, the spinner must still clear, or the
    // page is stranded on it (Decky keeps this component mounted).
    setBusyLabel(goVanilla ? `Switching ${game.name} to vanilla…` : `Re-enabling mods for ${game.name}…`);
    let res: Awaited<ReturnType<typeof applyVanillaMode>> | null = null;
    try {
      res = await applyVanillaMode(game, goVanilla);
      if (res.ok) {
        setUpdates([]);
        setSelectionMode(false);
      }
      await refresh();
    } catch (e) {
      console.error('[Moddy] vanilla toggle failed', e);
    } finally {
      setBusyLabel(null);
    }
    toaster.toast({
      title: 'Moddy',
      body: res?.ok
        ? (goVanilla ? `${game.name} is now unmodded — launch to play vanilla` : `Mods re-enabled for ${game.name}`)
        : 'Finished with some errors — check the log',
    });
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
        onToggleVanilla={(game.vanilla || game.installed_mods.length > 0 || game.modloader_installed) ? handleToggleVanilla : undefined}
        isVanilla={game.vanilla}
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
    // Thunderstore/BMI Browse: the whole catalog, client-paged through the shared paged tab (its
    // adapter caches + filters + slices the catalog; the list is not virtualized).
    ...(game.catalog_type && game.catalog_type !== 'nexus' && game.catalog_type !== 'ficsit' ? [{
      id: 'browse',
      title: 'Browse',
      content: (
        <BrowsePagedTab
          adapter={game.catalog_type === 'bmi' ? bmiAdapter : thunderstoreAdapter}
          game={game}
          onRefresh={refresh}
          filter={browseFilter}
          onFilterButton={handleBrowseFilterMenu}
          onCategories={setBrowseCategories}
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
    // Nexus + Workshop browse a server-paginated catalog via the shared (non-virtualized) paged tab.
    ...(game.catalog_type === 'nexus' ? [{
      id: 'browse',
      title: 'Browse',
      content: (
        // Key on the server-side filter inputs (Show NSFW + sort): changing either remounts the tab
        // so it re-fetches from page 1, since the in-place fetchKey effect doesn't re-run reliably
        // inside SteamUI's Tabs. The search term is lifted (initialSearch/onSearchChange) so it
        // survives the remount; client-side filters (hide-libraries/install-status) still apply live.
        <BrowsePagedTab
          key={`nexus-${nexusFilter.showNsfw}-${nexusFilter.sortBy}`}
          adapter={nexusAdapter}
          game={game}
          onRefresh={refresh}
          filter={nexusFilter}
          onFilterButton={handleNexusFilterMenu}
          ready={nsfwSeedResolved}
          initialSearch={nexusSearch}
          onSearchChange={setNexusSearch}
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
    // Collections: browse curated sets and install a whole one (its required mods at pinned files,
    // with the curator's installer choices replayed) as a single queued job. Venue-agnostic — the
    // adapter is picked from the game's venue (Nexus collections today; Thunderstore modpacks etc.
    // later), so this stays one top-level tab that lights up wherever the venue has a collections
    // concept. No per-item filter — adult collections are gated server-side by the NSFW setting.
    ...(venueHasCollections(game) && (collectionsProbed ?? COLLECTIONS_HINT[appid] ?? false) ? [{
      id: 'collections',
      title: 'Collections',
      content: (
        <BrowsePagedTab adapter={collectionsAdapterFor(game.catalog_type)!} game={game} onRefresh={refresh} />
      ),
      footer: {
        ...queueFooter,
        onMenuButton: handleOptionsMenu,
        onMenuActionDescription: 'Options',
      },
    }] : []),
    // ficsit.app (Satisfactory): server-paginated like Nexus (anonymous), with a sort/status filter.
    ...(game.catalog_type === 'ficsit' ? [{
      id: 'browse',
      title: 'Browse',
      content: (
        <BrowsePagedTab
          adapter={ficsitAdapter}
          game={game}
          onRefresh={refresh}
          filter={nexusFilter}
          onFilterButton={handleFicsitFilterMenu}
        />
      ),
      footer: {
        ...queueFooter,
        onMenuButton: handleOptionsMenu,
        onMenuActionDescription: 'Options',
        onSecondaryButton: handleFicsitFilterMenu,
        onSecondaryActionDescription: 'Filter',
      },
    }] : []),
    ...(game.modloader === 'steamworkshop' ? [{
      id: 'browse',
      title: 'Browse',
      content: (
        <BrowsePagedTab adapter={workshopAdapter} game={game} onRefresh={refresh} />
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
          <DownloadQueuePill appid={appid} />
        </div>
      )}
      {/* Force-Proton prompt: native-Linux games (e.g. Enter the Gungeon) run their native build by
          default, but Windows-built mods only load under Proton. Shown only when the game is installed,
          flagged requires_proton, and has no compat tool set yet — so it self-dismisses once fixed and
          never nags games that are already configured. */}
      {game?.installed && game.requires_proton && !game.current_compat_tool && !protonApplied && (
        <div style={{
          margin: '8px 12px', padding: '12px', borderRadius: '4px',
          background: 'var(--gpColorBgTertiary, rgba(255,255,255,0.05))', borderLeft: '3px solid #f8a623',
        }}>
          <div style={{ fontWeight: 'bold', marginBottom: '4px' }}>⚠ Proton required for mods</div>
          <div style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.85em', lineHeight: 1.5, marginBottom: '10px' }}>
            {game.name} has a native Linux build, but its mods are built for Windows and only load when
            the game runs through Proton. Set it to run with Proton, then launch the game once.
          </div>
          <DialogButton
            disabled={settingProton}
            onClick={async () => {
              setSettingProton(true);
              const tool = await setGameToProton(appid);
              setSettingProton(false);
              if (tool) {
                setProtonApplied(true);
                toaster.toast({ title: 'Moddy', body: `${game.name} set to run with Proton` });
                refresh();
              } else {
                toaster.toast({ title: 'Moddy', body: 'Set it in Steam: Properties → Compatibility → Force Proton' });
              }
            }}
          >
            {settingProton ? 'Setting…' : 'Set to Proton'}
          </DialogButton>
        </div>
      )}
      {/* A whole-page operation (vanilla toggle / reset) shows a spinner in place of the content,
          which both signals progress and freezes input until it completes. Otherwise: while vanilla,
          the tab area is replaced by a dedicated screen — this intercepts before the tab logic, which
          would otherwise show the Mod Loader *setup* tab (disabling the loader flips it to "not
          ready"). The Options menu's "Re-enable Mods" stays available too. */}
      {busyLabel ? (
        <div style={{ flex: 1, minHeight: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '12px' }}>
          <Spinner style={{ width: 32, height: 32 }} />
          <span style={{ color: 'var(--gpColorTextSecondary)' }}>{busyLabel}</span>
        </div>
      ) : game.vanilla ? (
        <VanillaView
          gameName={game.name}
          modCount={game.installed_mods.length}
          onReEnable={() => handleToggleVanilla(() => {})}
        />
      ) : (
        <div style={{ flex: 1, minHeight: 0 }}>
          <Tabs
            autoFocusContents
            activeTab={activeTab}
            onShowTab={(tab: string) => setSelectedTab(tab)}
            tabs={tabs}
          />
        </div>
      )}
    </div>
  );
};

export default ModPage;
