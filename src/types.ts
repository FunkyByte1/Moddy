import { callable } from '@decky/api';

export interface ModSource {
  type: string;
  owner: string;
  repo: string;
  asset: string;
  install_type?: string;  // "file" (default) or "zip_dir"
  workshop_id?: string;   // Steam Workshop published file id (type === 'steamworkshop')
}

export interface ModInfo {
  id: string;
  name: string;
  description: string;
  filename: string;
  source: ModSource;
  author?: string;
  homepage?: string;
  thumbnail?: string;
  modloader?: string;
  dependencies?: string[];  // list of mod IDs
  is_library?: boolean;     // a library/framework for other mods — hidden from lists by default
}

export interface ModMeta {
  name: string;
  author: string;
  description: string;
  homepage: string;
  thumbnail: string;
  modloader: string;
  dependencies: string[];
}

export interface InstalledMod {
  id: string;
  filename: string;
  enabled: boolean;
  version: string | null;
  meta?: ModMeta | null;
  is_library?: boolean;  // stamped by the backend from the catalog/frameworks
}

export interface ThunderstorePackageLatest {
  version_number: string;
  description: string;
  icon: string;
  dependencies: string[];
  download_url: string;
  file_size: number;
}

export interface ThunderstorePackage {
  name: string;
  full_name: string;
  owner: string;
  package_url: string;
  donation_link: string | null;
  date_updated: string;
  rating_score: number;
  is_deprecated: boolean;
  has_nsfw_content: boolean;
  categories: string[];
  latest: ThunderstorePackageLatest;
}

export interface ModRelease {
  version: string;
  name: string;
  published_at: string;
  download_urls: Record<string, string>;
}

export interface ModUpdate {
  id: string;
  installed_version: string;
  latest_version: string;
}

export interface ModloaderUpdate {
  installed: string;
  latest: string;
}

export interface ResetResult {
  ok: boolean;
  mods_removed: number;
  modloader_removed: boolean;
}

export interface GameStatus {
  id: string;
  name: string;
  appid: number;
  modloader: string;
  modloader_name: string;
  modloader_launch_options: string;
  modloader_needs_first_launch: boolean;
  // Frameworks bundled with the loader (e.g. Steamodded), shown on the Mod Loader tab.
  modloader_bundled: string[];
  thunderstore_community: string;
  // Which Browse catalog backs this game: 'bmi', 'thunderstore', 'nexus', or '' (Steam Workshop).
  catalog_type: string;
  // Catalog categories the UI treats as "library" (hidden from mod lists by default).
  library_categories: string[];
  installed: boolean;
  install_dir: string;
  modloader_installed: boolean;
  modloader_enabled: boolean;
  modloader_ready: boolean;
  installed_mods: InstalledMod[];
}

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
export const installModloader = callable<[appid: number, version: string | null], boolean>('install_modloader');
export const uninstallModloader = callable<[appid: number], boolean>('uninstall_modloader');
export const enableModloader = callable<[appid: number], boolean>('enable_modloader');
export const disableModloader = callable<[appid: number], boolean>('disable_modloader');
export const getModloaderVersion = callable<[appid: number], string | null>('get_modloader_version');
export const getModloaderReleases = callable<[appid: number], ModRelease[]>('get_modloader_releases');
export const checkModloaderUpdate = callable<[appid: number], ModloaderUpdate | null>('check_modloader_update');
export const cancelInstall = callable<[], void>('cancel_install');
export const resetGame = callable<[appid: number], ResetResult>('reset_game');
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
  callable<[appid: number, query: string, page: number, include_adult: boolean], ThunderstorePackage[]>('get_nexus_catalog');
// A selectable payload inside a multi-variant mod archive (e.g. the RE4 stack-size .pak options).
export interface NexusVariant { id: string; label: string }
export interface NeedsVariant { needs_variant: true; variants: NexusVariant[] }
// installNexusMod returns NeedsVariant when the archive bundles >1 variant and none was chosen —
// pass the chosen variant id back as the 4th arg to install just that one.
export const installNexusMod =
  callable<[appid: number, full_name: string, version: string | null, variant: string | null], boolean | null | string | NeedsVariant>('install_nexus_mod');

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

export interface WorkshopCatalogItem {
  id: string;
  name: string;
  description: string;
  preview_url: string;
  subscriptions: number;
  file_size: number;
  time_updated: number;
  tags: string[];
  url: string;
}
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

export interface ProfileMod {
  id: string;
  enabled: boolean;
  version: string | null;
}

export interface Profile {
  name: string;
  created_at: string;
  mods: ProfileMod[];
}

export const getProfiles = callable<[appid: number], Profile[]>('get_profiles');
export const saveProfile = callable<[appid: number, name: string], boolean>('save_profile');
export const renameProfile = callable<[appid: number, old_name: string, new_name: string], boolean>('rename_profile');
export const deleteProfile = callable<[appid: number, name: string], boolean>('delete_profile');