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
  ignore_unused?: boolean;  // user marked this library an intentional dep — excluded from the unused-libraries broom
  added_at?: number | null;  // unix seconds the mod was first installed; absent for legacy/untracked
  // Provenance for grouping: {sourceId -> {name, image}}. sourceId is "manual" or "collection:<slug>".
  // A mod brought in by a collection AND installed directly carries both. Absent = treat as "You".
  sources?: import('./lib/modSources').ModSources | null;
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
  is_library?: boolean;  // backend-stamped (Nexus: catalog.library_ids); Thunderstore filters via categories
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
  // True for native-Linux games whose Windows-built mods only load under Proton (e.g. Enter the
  // Gungeon). current_compat_tool is the tool Steam will run it with ('' = native, mods won't load).
  requires_proton: boolean;
  current_compat_tool: string;
  installed_mods: InstalledMod[];
  // True while the game is in "vanilla" (play-unmodded) mode — every mod + the modloader toggled
  // off but kept on disk, ready to switch back.
  vanilla: boolean;
  // External-merge games (Fields of Mistria/MOMI): true when a Steam game update wiped the mods
  // baked into the shared file, so the UI offers a one-tap "reapply mods".
  merge_tool_stale?: boolean;
  // True while a coalesced background rebuild is queued/running after mod changes — the shared game
  // file isn't baked yet, so the UI shows "Applying mods…" and warns against launching mid-rebuild.
  merge_tool_applying?: boolean;
}

export interface VanillaResult {
  ok: boolean;
  vanilla: boolean;
  noop?: boolean;
  mods_disabled?: number;
  mods_enabled?: number;
  modloader_id?: string | null;
  workshop?: string[]; // Workshop fileids the client must flip (not file-based)
}

// A selectable payload inside a multi-variant mod archive (e.g. the RE4 stack-size .pak options).
export interface NexusVariant { id: string; label: string }
// A collection's optional mod, offered while the install job is parked on the optional-mod checklist
// (only ones not already installed are offered).
export interface CollectionOption { id: string; name: string; file_id: string }
export interface NeedsVariant { needs_variant: true; variants: NexusVariant[] }

// ── FOMOD install wizard ───────────────────────────────────────────────────
// A FOMOD (scripted Nexus installer) with real choices parks the install and ships this serialized
// option-tree (backend fomod.serialize_for_ui). The wizard evaluates flag conditions client-side
// (steps appear/disappear, plugin states update) and resumes with the chosen plugin indices encoded
// as [[stepIdx, groupIdx, [pluginIdx, ...]], ...] through the same channel as a variant id.
export interface FomodCondition { op: string; flags: [string, string][]; children: FomodCondition[] }
export interface FomodPlugin {
  name: string;
  description: string;
  image: string | null;
  flags: [string, string][];                                  // condition flags set when selected
  type: { default: string; patterns: { cond: FomodCondition | null; type: string }[] };
}
export type FomodGroupType =
  'SelectExactlyOne' | 'SelectAtMostOne' | 'SelectAtLeastOne' | 'SelectAny' | 'SelectAll';
export interface FomodGroup { name: string; type: FomodGroupType | string; plugins: FomodPlugin[] }
export interface FomodStep { name: string; visible: FomodCondition | null; groups: FomodGroup[] }
export interface FomodModel {
  moduleName: string;
  steps: FomodStep[];
  default: [number, number, number[]][];                      // [stepIdx, groupIdx, pluginIdx[]]
}

// A Nexus collection in the in-app Collections browse list. Installing one enqueues its whole
// required mod set (pinned files + replayed FOMOD choices) as a single background job.
export interface CollectionItem {
  slug: string;
  name: string;
  author: string;
  summary: string;
  mod_count: number;
  endorsements: number;
  tile_image: string;
}

export interface CollectionModRef {
  mod_id: string;
  name: string;
  thumbnail: string;
  optional: boolean;
}

// A collection's full detail (name/image/description + its mods), fetched on demand for the
// Collections browse-tab detail and the Installed-tab collection panel.
export interface CollectionDetail {
  slug: string;
  name: string;
  image: string;
  summary: string;
  mod_count: number;
  mods: CollectionModRef[];
}

// ── Background download queue ──────────────────────────────────────────────
// Catalog installs that fetch archives server-side (Thunderstore / Nexus / BMI) are enqueued
// and drained by a single serial backend worker, so the UI can show a queue + per-item
// progress without blocking. Each enqueue returns immediately with a numeric job id. The
// `name` arg is the pretty display name (the frontend has it from the catalog item); the
// backend uses it for the queue row. Live state arrives via the `queue_state` / `queue_progress`
// events consumed by the downloadQueue store. (Workshop and modloader installs keep their own
// inline paths and are not queued.)
// 'needs_input' = parked mid-install awaiting a user choice (a Nexus variant). Workshop stays inline.
export type QueueStatus = 'queued' | 'downloading' | 'needs_input' | 'done' | 'failed' | 'cancelled';
export type QueueKind = 'thunderstore' | 'bmi' | 'nexus' | 'ficsit';
export interface QueueJob {
  job_id: number;
  appid: number;
  name: string;       // pretty display name
  ref: string;        // install id (full_name / mod_id) — match a catalog card to its job
  kind: QueueKind;
  status: QueueStatus;
  error: string;
  warning: string;    // non-fatal note, e.g. a best-effort dependency that didn't install
  percent: number;
  sub_label: string;   // package currently downloading within this job (a dep, or the mod itself)
  items_done: number;  // "N" — packages started in this job's cascade
  items_total: number; // "M" — total packages this job installs (0 = unknown / single)
  variants: NexusVariant[]; // present while status is 'needs_input' — the choices to offer
  multi_select?: boolean;   // the parked choice is a Nexus file picker (checklist), not a single-pick variant
  fomod?: FomodModel | null; // present while parked on a FOMOD install wizard (instead of variants)
  collection_options?: CollectionOption[]; // present while parked on a collection's optional-mod checklist
}

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
