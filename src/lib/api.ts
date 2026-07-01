import { callable } from '@decky/api';
import {
  GameStatus, ModRelease, ModloaderUpdate, ModUpdate, ResetResult, VanillaResult,
  NeedsVariant, QueueJob, ThunderstorePackage, WorkshopCatalogItem, Profile, CollectionItem,
  CollectionDetail,
} from '../types';

export const setLaunchOptions = (appid: number, options: string) => {
  (window as any).SteamClient.Apps.SetAppLaunchOptions(appid, options);
};

// Read the app's current Steam launch-options string (the field shared with the user).
export const getLaunchOptions = (appid: number): string =>
  (window as any).appDetailsStore?.GetAppDetails?.(appid)?.strLaunchOptions ?? '';

const tidyLaunchOptions = (s: string) => s.replace(/\s+/g, ' ').trim();

// Merge a modloader's launch-options fragment into the existing field instead of
// overwriting it, so any options the user set themselves survive. Idempotent: if our
// fragment is already present (e.g. re-enabling), the field is left untouched.
// A modloader template wraps the %command% placeholder (e.g.
// `WINEDLLOVERRIDES="winhttp=n,b" %command%`); the prefix carries env vars that must sit
// before the game command, so we ensure a %command% anchor exists and slot our parts
// around the user's.
export const addModloaderLaunchOptions = (appid: number, modloaderOptions: string) => {
  if (!modloaderOptions) return;
  const current = getLaunchOptions(appid);
  const [prefix = '', suffix = ''] = modloaderOptions.split('%command%').map(tidyLaunchOptions);
  if ((!prefix || current.includes(prefix)) && (!suffix || current.includes(suffix))) return;
  if (!current) {
    setLaunchOptions(appid, modloaderOptions);
    return;
  }
  // Keep the user's options on their original side of %command% (their env vars stay
  // before the command, their args after). With no anchor, the whole field is args.
  const anchor = current.indexOf('%command%');
  const userPre = anchor >= 0 ? tidyLaunchOptions(current.slice(0, anchor)) : '';
  const userPost = anchor >= 0 ? tidyLaunchOptions(current.slice(anchor + '%command%'.length)) : tidyLaunchOptions(current);
  const merged = [prefix, userPre, '%command%', userPost, suffix].filter(Boolean).join(' ');
  setLaunchOptions(appid, tidyLaunchOptions(merged));
};

// Remove only the fragment(s) a modloader contributes to the launch-options field,
// leaving any options the user added themselves intact. A modloader template wraps
// the %command% placeholder (e.g. `WINEDLLOVERRIDES="winhttp=n,b" %command%`); we
// strip the literal text on either side of %command% rather than clearing the field.
export const removeModloaderLaunchOptions = (appid: number, modloaderOptions: string) => {
  if (!modloaderOptions) return;
  const current = getLaunchOptions(appid);
  if (!current) return;
  const fragments = modloaderOptions.split('%command%').map(tidyLaunchOptions).filter(Boolean);
  let next = current;
  for (const frag of fragments) next = next.split(frag).join('');
  next = tidyLaunchOptions(next);
  // Nothing but the bare placeholder (or nothing) left → field is back to default.
  setLaunchOptions(appid, next === '%command%' ? '' : next);
};

// Self-heal the modloader's Steam launch option. Moddy sets it once, when the loader is installed
// from the Mod Loader tab — but a game reset, a SteamOS update, or a SetAppLaunchOptions that didn't
// persist can silently drop it, leaving the loader installed (winhttp.dll on disk) yet dormant, so
// BepInEx never injects and no mods load ("installed fine but nothing shows up"). Reapply the
// fragment whenever the loader is installed AND enabled; addModloaderLaunchOptions is idempotent, so
// this is a no-op once the option is present. Skipped in vanilla mode, where the loader is toggled
// off (modloader_enabled is false) and the option is intentionally absent.
export const ensureModloaderLaunchOptions = (game: GameStatus): void => {
  if (game.modloader_installed && game.modloader_enabled && game.modloader_launch_options) {
    addModloaderLaunchOptions(game.appid, game.modloader_launch_options);
  }
};

// ── Steam Play / Proton compatibility tool ────────────────────────────────────
// Native-Linux games (e.g. Enter the Gungeon) run their native build by default, but their mods
// are built for the Windows build (BepInEx injects via winhttp.dll), so they only load when the
// game is forced to run under Proton. Moddy can't set the compat tool from the Python backend —
// SpecifyCompatTool is a SteamClient method, same as the launch-options/Workshop calls above.

// Pick the compat tool to force a game onto: prefer Proton Experimental (the rolling latest,
// always present), else the newest-looking stock `proton_*`, else the first available tool.
const pickProtonTool = (tools: { strToolName: string }[]): string | undefined => {
  const names = tools.map(t => t.strToolName).filter(Boolean);
  if (names.includes('proton_experimental')) return 'proton_experimental';
  const stock = names.filter(n => n.toLowerCase().startsWith('proton_')).sort();
  return stock[stock.length - 1] ?? names[0];
};

// Force `appid` to run under Proton so Windows-built mods load. Enumerates the installed compat
// tools and applies the best Proton via SteamClient.Apps.SpecifyCompatTool. Returns the tool name
// applied, or '' if the SteamClient API was unavailable / no tool could be chosen.
export const setGameToProton = async (appid: number): Promise<string> => {
  const apps = (window as any).SteamClient?.Apps;
  if (typeof apps?.SpecifyCompatTool !== 'function') {
    console.error('[Moddy] SteamClient.Apps.SpecifyCompatTool unavailable');
    return '';
  }
  let tool = 'proton_experimental';
  try {
    if (typeof apps?.GetAvailableCompatTools === 'function') {
      const tools = await apps.GetAvailableCompatTools(appid);
      tool = pickProtonTool(tools ?? []) ?? tool;
    }
  } catch (e) {
    console.error('[Moddy] GetAvailableCompatTools failed; defaulting to proton_experimental', e);
  }
  apps.SpecifyCompatTool(appid, tool);
  return tool;
};

// ── Steam Workshop subscriptions ──────────────────────────────────────────────
// Workshop mods are installed by subscribing the running Steam client to the item
// — and that MUST happen here in the frontend via SteamClient, not in the Python
// backend. A backend process that calls SteamAPI_Init with the game's appid gets
// registered as "the game is running", which in Game Mode triggers the launch/exit
// transition (kicks back to home with the Steam logo). SteamClient.Apps.Subscribe-
// WorkshopItem is the same internal IPC the in-client Workshop button uses, so it
// has no such side effect. The backend still keeps the install record so Moddy can
// list/manage the mod; the actual subscribe/unsubscribe is done from here.
// Workshop subscriptions are tracked by a synthetic id: workshop.<appid>.<fileid>.
const workshopIdFor = (_appid: number, modId: string): string | undefined => {
  const m = modId.match(/^workshop\.\d+\.(\d+)$/);
  return m ? m[1] : undefined;
};

// The Moddy mod id used to install/track a Workshop file id.
export const workshopModId = (appid: number, fileId: string): string =>
  `workshop.${appid}.${fileId}`;

// The Workshop file id behind a synthetic Moddy mod id (workshop.<appid>.<fileid>), if any.
export const fileIdForMod = (appid: number, modId: string): string | undefined =>
  workshopIdFor(appid, modId);

const subscribeWorkshopItem = (appid: number, workshopId: string, subscribed: boolean): void => {
  const apps = (window as any).SteamClient?.Apps;
  if (typeof apps?.SubscribeWorkshopItem === 'function') {
    // id is a decimal 64-bit string; subscribed=true adds (auto-downloads), false removes.
    apps.SubscribeWorkshopItem(appid, String(workshopId), subscribed);
  } else {
    console.error('[Moddy] SteamClient.Apps.SubscribeWorkshopItem unavailable');
  }
};

// Locally enable/disable a subscribed Workshop item WITHOUT unsubscribing (files stay,
// no re-download). The Steam method takes `disabled`, so enabling passes false.
const setWorkshopItemDisabled = (appid: number, workshopId: string, disabled: boolean): void => {
  const apps = (window as any).SteamClient?.Apps;
  if (typeof apps?.SetWorkshopItemsDisabledLocally === 'function') {
    apps.SetWorkshopItemsDisabledLocally(appid, [String(workshopId)], disabled);
  } else {
    console.error('[Moddy] SteamClient.Apps.SetWorkshopItemsDisabledLocally unavailable');
  }
};

// Callables
export const getSupportedAppids = callable<[], number[]>('get_supported_appids');

const workshopFileId = (it: any): string =>
  String(it?.publishedfileid ?? it?.ulPublishedFileID ?? '');

// Normalize a SteamClient WorkshopItem (rich variant) to what the backend reconcile
// expects. `children` carries the item's required items (its dependencies).
const normalizeWorkshopItem = (it: any) => ({
  id: workshopFileId(it),
  name: it?.title ?? '',
  thumbnail: it?.preview_url ?? '',
  description: it?.short_description ?? '',
  dependencies: (Array.isArray(it?.children) ? it.children : []).map((c: any) =>
    typeof c === 'string' ? c : workshopFileId(c)).filter(Boolean),
});

// Read the user's actual subscriptions for an app, normalized. Returns null if the
// query failed/unavailable so callers SKIP reconciling — an empty array would be read
// as "nothing subscribed" and wipe the tracked set. GetSubscribedWorkshopItems is often
// "lean" (ids only), so we enrich titles/previews/children via the details call.
const getSubscribedWorkshopItems = async (appid: number): Promise<ReturnType<typeof normalizeWorkshopItem>[] | null> => {
  const apps = (window as any).SteamClient?.Apps;
  if (typeof apps?.GetSubscribedWorkshopItems !== 'function') return null;
  try {
    const subs = await apps.GetSubscribedWorkshopItems(appid);
    const ids = (Array.isArray(subs) ? subs : []).map(workshopFileId).filter(Boolean);
    if (ids.length === 0) return [];
    const byId = new Map<string, any>();
    if (typeof apps.GetSubscribedWorkshopItemDetails === 'function') {
      try {
        const det = await apps.GetSubscribedWorkshopItemDetails(appid, ids);
        const list = Array.isArray(det) ? det
          : Array.isArray(det?.items) ? det.items
          : Array.isArray(det?.response) ? det.response : [];
        for (const d of list) { const id = workshopFileId(d); if (id) byId.set(id, d); }
      } catch (e) { console.error('[Moddy] GetSubscribedWorkshopItemDetails failed', e); }
    }
    return ids.map(id => normalizeWorkshopItem({ ...(byId.get(id) || {}), publishedfileid: id }));
  } catch (e) {
    console.error('[Moddy] GetSubscribedWorkshopItems failed', e);
    return null;
  }
};

const reconcileWorkshopSubscriptions =
  callable<[appid: number, items: any[]], boolean>('reconcile_workshop_subscriptions');

const _getSupportedGames = callable<[], GameStatus[]>('get_supported_games');
// Wrapper: reconcile each Workshop game's tracked list against the user's real Steam
// subscriptions (captures auto-installed deps and mods subscribed/unsubscribed outside
// Moddy). Re-fetches once if anything changed so the returned data reflects the synced state.
export const getSupportedGames = async (): Promise<GameStatus[]> => {
  let games = await _getSupportedGames();
  let changed = false;
  for (const g of games) {
    if (g.modloader !== 'steamworkshop') continue;
    const items = await getSubscribedWorkshopItems(g.appid);
    if (items === null) continue;  // query failed — don't reconcile against an empty set
    if (await reconcileWorkshopSubscriptions(g.appid, items)) changed = true;
  }
  if (changed) {
    games = await _getSupportedGames();
  }
  return games;
};

const _getGameStatus = callable<[appid: number], GameStatus | null>('get_game_status');
// Single-game status for the per-mod-action refresh (only the configured game is on
// screen), avoiding a full all-games rebuild on every toggle. Mirrors the Workshop
// reconciliation in getSupportedGames, but scoped to just this game.
export const getGameStatus = async (appid: number): Promise<GameStatus | null> => {
  let game = await _getGameStatus(appid);
  if (game && game.modloader === 'steamworkshop') {
    const items = await getSubscribedWorkshopItems(appid);
    if (items !== null && await reconcileWorkshopSubscriptions(appid, items)) {
      game = await _getGameStatus(appid);
    }
  }
  return game;
};
// Returns true on success, false on failure, or the string 'premium_required' when a Nexus-sourced
// loader (e.g. Stracker's Loader for MHW) needs a Nexus Premium account to download.
export const installModloader = callable<[appid: number, version: string | null], boolean | string>('install_modloader');
export const uninstallModloader = callable<[appid: number], boolean>('uninstall_modloader');
export const getModloaderUninstallImpact = callable<[appid: number], { id: string; name: string }[]>('get_modloader_uninstall_impact');
export const enableModloader = callable<[appid: number], boolean>('enable_modloader');
export const disableModloader = callable<[appid: number], boolean>('disable_modloader');
export const getModloaderVersion = callable<[appid: number], string | null>('get_modloader_version');
export const getModloaderReleases = callable<[appid: number], ModRelease[]>('get_modloader_releases');
export const checkModloaderUpdate = callable<[appid: number], ModloaderUpdate | null>('check_modloader_update');
export const cancelInstall = callable<[], void>('cancel_install');
export const resetGame = callable<[appid: number], ResetResult>('reset_game');

const _setGameVanillaMode = callable<[appid: number, vanilla: boolean], VanillaResult>('set_game_vanilla_mode');

// Switch a game to/from unmodded without deleting anything. The backend toggles file-based mods and
// the modloader and reports what to finish on the client: flip the modloader's launch options (so the
// loader actually stops/starts injecting — and for SMAPI, this IS the off switch), and locally
// enable/disable the Workshop items it returns (Steam owns those, not the filesystem).
export const applyVanillaMode = async (game: GameStatus, vanilla: boolean): Promise<VanillaResult> => {
  const res = await _setGameVanillaMode(game.appid, vanilla);
  if (!res.ok && !res.noop) return res;
  if (res.modloader_id && game.modloader_launch_options) {
    if (vanilla) removeModloaderLaunchOptions(game.appid, game.modloader_launch_options);
    else addModloaderLaunchOptions(game.appid, game.modloader_launch_options);
  }
  for (const fileid of res.workshop ?? []) {
    setWorkshopItemDisabled(game.appid, fileid, vanilla); // disabled=true when going vanilla
  }
  return res;
};
const _installMod = callable<[appid: number, mod_id: string, version: string | null], boolean | null>('install_mod');
// Workshop mods: subscribe via SteamClient first (an item's required items are resolved
// and subscribed by installWorkshopTree), then record via the backend.
export const installMod = async (
  appid: number, mod_id: string, version: string | null,
): Promise<boolean | null> => {
  const wid = workshopIdFor(appid, mod_id);
  if (wid) subscribeWorkshopItem(appid, wid, true);
  return _installMod(appid, mod_id, version);
};

const _uninstallMod = callable<[appid: number, mod_id: string], boolean>('uninstall_mod');
export const uninstallMod = async (appid: number, mod_id: string): Promise<boolean> => {
  const wid = workshopIdFor(appid, mod_id);
  if (wid) subscribeWorkshopItem(appid, wid, false);
  return _uninstallMod(appid, mod_id);
};
const _toggleMod = callable<[appid: number, mod_id: string, enable: boolean], boolean>('toggle_mod');
// Workshop mods: flip the local disabled flag via SteamClient (no unsubscribe), then
// let the backend persist the enabled state into its record.
export const toggleMod = async (appid: number, mod_id: string, enable: boolean): Promise<boolean> => {
  const wid = workshopIdFor(appid, mod_id);
  if (wid) setWorkshopItemDisabled(appid, wid, !enable);
  return _toggleMod(appid, mod_id, enable);
};
// Mark an installed library as an intentional (undocumented) dependency so the unused-libraries
// cleanup ("broom") stops flagging it — or clear that mark. Keyed by mod id (game-agnostic backend).
export const setLibraryIgnored = callable<[mod_id: string, ignored: boolean], boolean>('set_library_ignored');
export const getModReleases = callable<[appid: number, mod_id: string], ModRelease[]>('get_mod_releases');
export const checkModUpdates = callable<[appid: number], ModUpdate[]>('check_mod_updates');
export const getBackedUpVersions = callable<[appid: number, mod_id: string], string[]>('get_backed_up_versions');
export const deleteModVersion = callable<[appid: number, mod_id: string, version: string], boolean>('delete_mod_version');
export const getThunderstoreCatalog = callable<[appid: number], ThunderstorePackage[]>('get_thunderstore_catalog');
export const refreshThunderstoreCatalog = callable<[appid: number], boolean>('refresh_thunderstore_catalog');
// with_deps=false installs only the named mod, leaving its dependencies out ("skip deps").
export const installThunderstoreMod = callable<[appid: number, full_name: string, version: string | null, with_deps?: boolean], boolean | null>('install_thunderstore_mod');
// Balatro Mod Index (BMI) catalog — same ThunderstorePackage item shape as Thunderstore.
export const getBmiCatalog = callable<[appid: number], ThunderstorePackage[]>('get_bmi_catalog');
export const refreshBmiCatalog = callable<[appid: number], boolean>('refresh_bmi_catalog');
export const installBmiMod = callable<[appid: number, mod_id: string, version: string | null], boolean | null>('install_bmi_mod');
export const getBrowseDenylist = callable<[], string[]>('get_browse_denylist');

// Nexus Mods catalog — server-paginated/searched (~25 items per page), returned in the
// shared ThunderstorePackage item shape. installNexusMod resolves a Premium CDN download
// link; it returns the string 'premium_required' when the configured key isn't Premium.
export const getNexusCatalog =
  callable<[appid: number, query: string, page: number, include_adult: boolean, sort: string], ThunderstorePackage[]>('get_nexus_catalog');
// installNexusMod returns NeedsVariant when the archive bundles >1 variant and none was chosen —
// pass the chosen variant id back as the 4th arg to install just that one.
export const installNexusMod =
  callable<[appid: number, full_name: string, version: string | null, variant: string | null], boolean | null | string | NeedsVariant>('install_nexus_mod');

// ── Background download queue ──────────────────────────────────────────────
// Catalog installs that fetch archives server-side (Thunderstore / Nexus / BMI) are enqueued
// and drained by a single serial backend worker, so the UI can show a queue + per-item
// progress without blocking. Each enqueue returns immediately with a numeric job id. The
// `name` arg is the pretty display name (the frontend has it from the catalog item); the
// backend uses it for the queue row. Live state arrives via the `queue_state` / `queue_progress`
// events consumed by the downloadQueue store. (Workshop and modloader installs keep their own
// inline paths and are not queued.)
// 'needs_input' = parked mid-install awaiting a user choice (a Nexus variant). Workshop stays inline.
export const enqueueThunderstore =
  callable<[appid: number, full_name: string, name: string, version: string | null, with_deps?: boolean, allow_missing?: boolean], number>('enqueue_thunderstore');
// Declared dependencies of a Thunderstore mod that aren't in the catalog (refreshes once before
// reporting, to rule out a stale cache). Empty = all resolvable. Used to warn / offer "install anyway".
export const getUnresolvedDependencies =
  callable<[appid: number, full_name: string, with_deps?: boolean], string[]>('get_unresolved_dependencies');
export const enqueueBmi =
  callable<[appid: number, mod_id: string, name: string, version: string | null], number>('enqueue_bmi');
export const enqueueNexus =
  callable<[appid: number, full_name: string, name: string, version: string | null], number>('enqueue_nexus');
// Install a whole Nexus collection (its required mods at pinned files, with the curator's FOMOD
// choices replayed) as one background job. `ref` is a collection URL or slug. Returns the job id,
// or -1 if the game isn't a Nexus game / the ref is unparseable or for a different game.
export const enqueueCollection =
  callable<[appid: number, ref: string], number>('enqueue_collection');
// A page (~25) of Nexus collections for the game's Collections browse tab.
export const getCollectionsCatalog =
  callable<[appid: number, query: string, page: number], CollectionItem[]>('get_collections_catalog');
// Whether the game's Nexus venue has ANY collections (adult or not) — gates whether the Collections
// tab shows at all, independent of the NSFW setting (the list inside still filters NSFW).
export const gameHasCollections =
  callable<[appid: number], boolean>('game_has_collections');
// A collection's detail — name/image/description + its mod list (name + thumbnail + optional). One
// light GraphQL call; drives the browse-tab "mods in this collection" list and the Installed-tab panel.
export const getCollectionDetail =
  callable<[appid: number, slug: string], CollectionDetail>('get_collection_detail');
// Preview a collection uninstall: {remove, keep} display-name lists (keep = mods also installed
// manually or in another collection, so they'd be kept). Lets the UI warn before removing.
export const previewUninstallCollection =
  callable<[slug: string], { remove: string[]; keep: string[] }>('preview_uninstall_collection');
// Ref-counted "remove this collection": drops each member's collection:<slug> tag, uninstalls a mod
// only if that was its last source. Returns {removed, kept} mod-id lists.
export const uninstallCollection =
  callable<[appid: number, slug: string], { removed: string[]; kept: string[] }>('uninstall_collection');
// ficsit.app (Satisfactory) catalog — server-paginated/searched (~25 items per page), in the shared
// ThunderstorePackage item shape. Anonymous (no API key); installs cascade dependencies server-side
// and are drained by the same background queue as Nexus/Thunderstore (kind 'ficsit').
export const getFicsitCatalog =
  callable<[appid: number, query: string, page: number, sort: string], ThunderstorePackage[]>('get_ficsit_catalog');
export const enqueueFicsit =
  callable<[appid: number, full_name: string, name: string, version: string | null], number>('enqueue_ficsit');
// Resume a job parked on a variant choice (status 'needs_input'); installs from the cached archive.
export const resumeDownloadJob = callable<[job_id: number, variant: string], boolean>('resume_download_job');
export const cancelDownloadJob = callable<[job_id: number], boolean>('cancel_download_job');
export const clearDownloadJob = callable<[job_id: number], boolean>('clear_download_job');
// Clears finished (done/failed/cancelled) jobs. Pass an appid to clear only that game's finished
// jobs — the queue panel is per-game, so "Clear finished" must not wipe another game's outcomes.
export const clearFinishedDownloads = callable<[appid?: number], void>('clear_finished_downloads');
export const getDownloadQueue = callable<[], QueueJob[]>('get_download_queue');

// Account-global plugin settings (e.g. the Nexus API key). Stored plaintext in the
// plugin's settings dir; the key is account-wide, not per-game.
export const getSetting = callable<[key: string], any>('get_setting');
export const setSetting = callable<[key: string, value: any], boolean>('set_setting');
export const NEXUS_API_KEY = 'nexus_api_key';
// Account-global gate for NSFW content. When off, the per-game Browse filter hides the
// "Show NSFW" control and NSFW mods stay filtered out; when on, it's offered per-session.
export const NSFW_ENABLED = 'nsfw_enabled';
// Sub-setting (only meaningful when NSFW_ENABLED): seed each game's Browse filter with
// "Show NSFW" already on, instead of off. Still toggleable per-session.
export const NSFW_DEFAULT_ON = 'nsfw_default_on';

// Bundles logs into a zip on the Deck's Desktop and returns the path (or null on failure).
export const exportLogs = callable<[], string | null>('export_logs');

// Steam Workshop browse — server-paginated/searched (~30 items per page).
export const getWorkshopCatalog =
  callable<[appid: number, search: string, sort: string, page: number], WorkshopCatalogItem[]>('get_workshop_catalog');

// An item's declared required items (dependencies), with metadata. SteamClient.Subscribe-
// WorkshopItem doesn't cascade these, so Moddy resolves and subscribes them itself.
export const getWorkshopRequiredItems =
  callable<[appid: number, fileid: string], WorkshopCatalogItem[]>('get_workshop_required_items');

// Stamp real metadata onto a just-installed Workshop record so it shows its name
// immediately instead of the "Workshop item <id>" placeholder until the next reconcile.
export const setWorkshopMeta =
  callable<[appid: number, fileid: string, name: string, thumbnail: string, description: string], boolean>('set_workshop_meta');

// Install a Workshop item and its declared required items (deps), recursively, stamping
// each one's real name immediately so deps never show the "Workshop item <id>" placeholder.
export const installWorkshopTree = async (
  appid: number, fileId: string,
  meta?: { name?: string; thumbnail?: string; description?: string },
  seen: Set<string> = new Set(),
  withDeps: boolean = true,
): Promise<void> => {
  if (seen.has(fileId)) return;
  seen.add(fileId);
  await installMod(appid, workshopModId(appid, fileId), null);
  if (meta?.name) await setWorkshopMeta(appid, fileId, meta.name, meta.thumbnail ?? '', meta.description ?? '');
  // withDeps=false ("skip dependencies") subscribes only this item, not its required items.
  if (!withDeps) return;
  for (const req of await getWorkshopRequiredItems(appid, fileId)) {
    await installWorkshopTree(appid, req.id, { name: req.name, thumbnail: req.preview_url, description: req.description }, seen);
  }
};

export const getProfiles = callable<[appid: number], Profile[]>('get_profiles');
export const saveProfile = callable<[appid: number, name: string], boolean>('save_profile');
export const renameProfile = callable<[appid: number, old_name: string, new_name: string], boolean>('rename_profile');
export const deleteProfile = callable<[appid: number, name: string], boolean>('delete_profile');
