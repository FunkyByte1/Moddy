import { callable } from '@decky/api';

export interface ModSource {
  type: string;
  owner: string;
  repo: string;
  asset: string;
  install_type?: string;  // "file" (default) or "zip_dir"
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
  thunderstore_community: string;
  // Which Browse catalog backs this game: 'bmi', 'thunderstore', or '' (curated-only).
  catalog_type: string;
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

// Callables
export const getSupportedAppids = callable<[], number[]>('get_supported_appids');
export const getSupportedGames = callable<[], GameStatus[]>('get_supported_games');
export const installModloader = callable<[appid: number, version: string | null], boolean>('install_modloader');
export const uninstallModloader = callable<[appid: number], boolean>('uninstall_modloader');
export const enableModloader = callable<[appid: number], boolean>('enable_modloader');
export const disableModloader = callable<[appid: number], boolean>('disable_modloader');
export const getModloaderVersion = callable<[appid: number], string | null>('get_modloader_version');
export const getModloaderReleases = callable<[appid: number], ModRelease[]>('get_modloader_releases');
export const checkModloaderUpdate = callable<[appid: number], ModloaderUpdate | null>('check_modloader_update');
export const cancelInstall = callable<[], void>('cancel_install');
export const resetGame = callable<[appid: number], ResetResult>('reset_game');
export const installMod = callable<[appid: number, mod_id: string, version: string | null], boolean | null>('install_mod');
export const uninstallMod = callable<[appid: number, mod_id: string], boolean>('uninstall_mod');
export const toggleMod = callable<[appid: number, mod_id: string, enable: boolean], boolean>('toggle_mod');
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