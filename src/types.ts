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
const _workshopIds = new Map<string, string>();     // `${appid}:${mod_id}` -> publishedfileid
const _workshopDeps = new Map<string, string[]>();  // `${appid}:${mod_id}` -> dependency mod ids
const _workshopIdToMod = new Map<string, string>(); // `${appid}:${fileid}` -> curated mod id

const workshopIdFor = (appid: number, modId: string): string | undefined => {
  const direct = _workshopIds.get(`${appid}:${modId}`);
  if (direct) return direct;
  // Non-curated reconciled subscriptions use a synthetic id: workshop.<appid>.<fileid>
  const m = modId.match(/^workshop\.\d+\.(\d+)$/);
  return m ? m[1] : undefined;
};

// The Moddy mod id used to install/track a Workshop file id: the curated id when one
// matches (so browse installs dedupe against curated mods), else the synthetic id.
export const workshopModId = (appid: number, fileId: string): string =>
  _workshopIdToMod.get(`${appid}:${fileId}`) ?? `workshop.${appid}.${fileId}`;

// The Workshop file id behind a Moddy mod id (curated or synthetic), if any.
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

const indexWorkshopMods = (games: GameStatus[]): void => {
  for (const g of games) {
    for (const m of g.mods || []) {
      if (m.source?.type === 'steamworkshop' && m.source.workshop_id) {
        _workshopIds.set(`${g.appid}:${m.id}`, m.source.workshop_id);
        _workshopDeps.set(`${g.appid}:${m.id}`, m.dependencies || []);
        _workshopIdToMod.set(`${g.appid}:${m.source.workshop_id}`, m.id);
      }
    }
  }
};

const _getSupportedGames = callable<[], GameStatus[]>('get_supported_games');
// Wrapper: index curated Workshop mods, then reconcile each Workshop game's tracked
// list against the user's real Steam subscriptions (captures auto-installed deps and
// mods subscribed/unsubscribed outside Moddy). Re-fetches once if anything changed so
// the returned data reflects the synced state.
export const getSupportedGames = async (): Promise<GameStatus[]> => {
  let games = await _getSupportedGames();
  indexWorkshopMods(games);
  let changed = false;
  for (const g of games) {
    if (g.modloader !== 'steamworkshop') continue;
    const items = await getSubscribedWorkshopItems(g.appid);
    if (items === null) continue;  // query failed — don't reconcile against an empty set
    if (await reconcileWorkshopSubscriptions(g.appid, items)) changed = true;
  }
  if (changed) {
    games = await _getSupportedGames();
    indexWorkshopMods(games);
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

// Nexus Mods catalog — server-paginated/searched (~25 items per page), returned in the
// shared ThunderstorePackage item shape. installNexusMod resolves a Premium CDN download
// link; it returns the string 'premium_required' when the configured key isn't Premium.
export const getNexusCatalog =
  callable<[appid: number, query: string, page: number], ThunderstorePackage[]>('get_nexus_catalog');
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

// Stamp real metadata onto a just-installed non-curated record so it shows its name
// immediately instead of the "Workshop item <id>" placeholder until the next reconcile.
export const setWorkshopMeta =
  callable<[appid: number, fileid: string, name: string, thumbnail: string, description: string], boolean>('set_workshop_meta');

// Install a Workshop item and its declared required items (deps), recursively, stamping
// each one's real name immediately so deps never show the "Workshop item <id>" placeholder.
export const installWorkshopTree = async (
  appid: number, fileId: string,
  meta?: { name?: string; thumbnail?: string; description?: string },
  seen: Set<string> = new Set(),
): Promise<void> => {
  if (seen.has(fileId)) return;
  seen.add(fileId);
  await installMod(appid, workshopModId(appid, fileId), null);
  if (meta?.name) await setWorkshopMeta(appid, fileId, meta.name, meta.thumbnail ?? '', meta.description ?? '');
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