import { ModInfo } from '../types';
import { ModSources } from '../lib/modSources';

export interface ModEntry {
  id: string;
  name: string;
  installed: boolean;
  enabled: boolean;
  version: string | null;
  hasUpdate: boolean;
  dependenciesMet: boolean;
  isLibrary: boolean;
  ignoreUnused: boolean;  // user marked this library an intentional dep — excluded from the unused-libraries broom
  addedAt: number;  // unix seconds first installed; 0 if unknown (legacy/untracked mods)
  // Provenance for the Installed page: {sourceId -> {name, image}}, sourceId "manual" or
  // "collection:<slug>". A row shows a "from <collection>" tag when a collection brought it in.
  sources?: ModSources | null;
  info: ModInfo;
}