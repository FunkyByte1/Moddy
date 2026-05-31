import { callable } from '@decky/api';

export interface ModInfo {
  name: string;
  description: string;
  url: string;
  filename: string;
  author?: string;
  homepage?: string;
  thumbnail?: string;
  dependencies?: string[];
}

export interface InstalledMod {
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
  filename: string;
  installed_version: string;
  latest_version: string;
}

export interface GameStatus {
  name: string;
  appid: number;
  modloader: string;
  installed: boolean;
  install_dir: string;
  modloader_installed: boolean;
  modloader_enabled: boolean;
  modloader_ready: boolean;
  installed_mods: InstalledMod[];
  recommended_mods: ModInfo[];
}

export const MODLOADER_LAUNCH_OPTIONS: Record<string, string> = {
  melonloader: 'WINEDLLOVERRIDES="version=n,b" %command%',
};

export const setLaunchOptions = (appid: number, options: string) => {
  (window as any).SteamClient.Apps.SetAppLaunchOptions(appid, options);
};

// Callables
export const getSupportedGames = callable<[], GameStatus[]>('get_supported_games');
export const installModloader = callable<[appid: number], boolean>('install_modloader');
export const uninstallModloader = callable<[appid: number], boolean>('uninstall_modloader');
export const enableModloader = callable<[appid: number], boolean>('enable_modloader');
export const disableModloader = callable<[appid: number], boolean>('disable_modloader');
export const cancelInstall = callable<[], void>('cancel_install');
export const installMod = callable<[appid: number, mod_filename: string, version: string | null], boolean>('install_mod');
export const uninstallMod = callable<[appid: number, mod_filename: string], boolean>('uninstall_mod');
export const toggleMod = callable<[appid: number, mod_filename: string, enable: boolean], boolean>('toggle_mod');
export const getModReleases = callable<[mod_url: string, mod_filename: string], ModRelease[]>('get_mod_releases');
export const checkModUpdates = callable<[appid: number], ModUpdate[]>('check_mod_updates');