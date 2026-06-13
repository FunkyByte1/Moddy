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
  // Which Browse catalog backs this game: 'bmi', 'thunderstore', or '' (curated-only).
  catalog_type: string;
  // Catalog categories the UI treats as "library" (hidden from mod lists by default).
  library_categories: string[];
  installed: boolean;
  install_dir: string;
  modloader_installed: boolean;
  modloader_enabled: boolean;
  modloader_ready: boolean;
  installed_mods: InstalledMod[];
  mods: ModInfo[];
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
const _workshopIds = new Map<string, string>();    // `${appid}:${mod_id}` -> publishedfileid
const _workshopDeps = new Map<string, string[]>(); // `${appid}:${mod_id}` -> dependency mod ids

const workshopIdFor = (appid: number, modId: string): string | undefined =>
  _workshopIds.get(`${appid}:${modId}`);

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

const _getSupportedGames = callable<[], GameStatus[]>('get_supported_games');
// Wrapper: keep the workshop id lookup current from each game's curated mod list.
export const getSupportedGames = async (): Promise<GameStatus[]> => {
  const games = await _getSupportedGames();
  for (const g of games) {
    for (const m of g.mods || []) {
      if (m.source?.type === 'steamworkshop' && m.source.workshop_id) {
        _workshopIds.set(`${g.appid}:${m.id}`, m.source.workshop_id);
        _workshopDeps.set(`${g.appid}:${m.id}`, m.dependencies || []);
      }
    }
  }
  return games;
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
// Workshop mods: subscribe declared dependencies first (each is itself a curated Workshop
// mod), then the mod, then record via the backend. Steam also auto-subscribes an author's
// declared "required items", but resolving deps here covers ones the author didn't link on
// the Workshop and makes Moddy actually track them. `seen` guards against cycles.
export const installMod = async (
  appid: number, mod_id: string, version: string | null, seen: Set<string> = new Set(),
): Promise<boolean | null> => {
  const wid = workshopIdFor(appid, mod_id);
  if (wid) {
    seen.add(mod_id);
    for (const dep of _workshopDeps.get(`${appid}:${mod_id}`) || []) {
      if (!seen.has(dep) && workshopIdFor(appid, dep)) {
        await installMod(appid, dep, null, seen);
      }
    }
    subscribeWorkshopItem(appid, wid, true);
  }
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
export const installThunderstoreMod = callable<[appid: number, full_name: string, version: string | null], boolean | null>('install_thunderstore_mod');
// Balatro Mod Index (BMI) catalog — same ThunderstorePackage item shape as Thunderstore.
export const getBmiCatalog = callable<[appid: number], ThunderstorePackage[]>('get_bmi_catalog');
export const refreshBmiCatalog = callable<[appid: number], boolean>('refresh_bmi_catalog');
export const installBmiMod = callable<[appid: number, mod_id: string, version: string | null], boolean | null>('install_bmi_mod');
export const getBrowseDenylist = callable<[], string[]>('get_browse_denylist');

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