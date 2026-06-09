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

export interface InstalledMod {
  id: string;
  filename: string;
  enabled: boolean;
  version: string | null;
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

export interface GameStatus {
  id: string;
  name: string;
  appid: number;
  modloader: string;
  modloader_name: string;
  installed: boolean;
  install_dir: string;
  modloader_installed: boolean;
  modloader_enabled: boolean;
  modloader_ready: boolean;
  installed_mods: InstalledMod[];
  mods: ModInfo[];
}

export const MODLOADER_LAUNCH_OPTIONS: Record<string, string> = {
  melonloader: 'WINEDLLOVERRIDES="version=n,b" %command%',
  lovely: 'WINEDLLOVERRIDES="version=n,b" %command%',
  bepinex: 'WINEDLLOVERRIDES="winhttp=n,b" %command%',
};

export const setLaunchOptions = (appid: number, options: string) => {
  (window as any).SteamClient.Apps.SetAppLaunchOptions(appid, options);
};

// Callables
export const getSupportedGames = callable<[], GameStatus[]>('get_supported_games');
export const installModloader = callable<[appid: number, version: string | null], boolean>('install_modloader');
export const uninstallModloader = callable<[appid: number], boolean>('uninstall_modloader');
export const enableModloader = callable<[appid: number], boolean>('enable_modloader');
export const disableModloader = callable<[appid: number], boolean>('disable_modloader');
export const getModloaderVersion = callable<[appid: number], string | null>('get_modloader_version');
export const getModloaderReleases = callable<[appid: number], ModRelease[]>('get_modloader_releases');
export const checkModloaderUpdate = callable<[appid: number], ModloaderUpdate | null>('check_modloader_update');
export const cancelInstall = callable<[], void>('cancel_install');
export const installMod = callable<[appid: number, mod_id: string, version: string | null], boolean | null>('install_mod');
export const uninstallMod = callable<[appid: number, mod_id: string], boolean>('uninstall_mod');
export const toggleMod = callable<[appid: number, mod_id: string, enable: boolean], boolean>('toggle_mod');
export const getModReleases = callable<[appid: number, mod_id: string], ModRelease[]>('get_mod_releases');
export const checkModUpdates = callable<[appid: number], ModUpdate[]>('check_mod_updates');
export const getBackedUpVersions = callable<[appid: number, mod_id: string], string[]>('get_backed_up_versions');
export const deleteModVersion = callable<[appid: number, mod_id: string, version: string], boolean>('delete_mod_version');