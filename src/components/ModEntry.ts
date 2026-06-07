import { ModInfo } from '../types';

export interface ModEntry {
  id: string;
  name: string;
  installed: boolean;
  enabled: boolean;
  version: string | null;
  hasUpdate: boolean;
  dependenciesMet: boolean;
  info: ModInfo;
}