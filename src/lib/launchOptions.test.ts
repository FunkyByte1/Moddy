import { describe, it, expect, beforeEach } from 'vitest';
import { ensureModloaderLaunchOptions, addModloaderLaunchOptions } from './api';
import { GameStatus } from '../types';

// The modloader launch option is the per-app Steam setting that makes BepInEx's winhttp inject under
// Proton (WINEDLLOVERRIDES="winhttp=n,b" %command%). Moddy self-heals it: whenever the loader is
// installed+enabled, reapply the fragment idempotently and preserve the user's own options — so a
// reset / OS update / non-persisted SetAppLaunchOptions can't leave the loader on disk but dormant.
// SteamClient + appDetailsStore are mocked to a single in-memory launch-options string.

const BEPINEX = 'WINEDLLOVERRIDES="winhttp=n,b" %command%';

let current: string;
let sets: string[];

beforeEach(() => {
  current = '';
  sets = [];
  (window as any).appDetailsStore = { GetAppDetails: () => ({ strLaunchOptions: current }) };
  (window as any).SteamClient = {
    Apps: { SetAppLaunchOptions: (_appid: number, opts: string) => { current = opts; sets.push(opts); } },
  };
});

const game = (over: Partial<GameStatus> = {}): GameStatus => ({
  appid: 1,
  modloader_installed: true,
  modloader_enabled: true,
  modloader_launch_options: BEPINEX,
  ...over,
} as unknown as GameStatus);

describe('ensureModloaderLaunchOptions (self-heal)', () => {
  it('sets the loader option when installed+enabled and it is missing', () => {
    ensureModloaderLaunchOptions(game());
    expect(current).toBe(BEPINEX);
    expect(sets).toHaveLength(1);
  });

  it('is a no-op when the option is already present', () => {
    current = BEPINEX;
    ensureModloaderLaunchOptions(game());
    expect(sets).toHaveLength(0);
  });

  it('does nothing when the loader is not installed', () => {
    ensureModloaderLaunchOptions(game({ modloader_installed: false }));
    expect(sets).toHaveLength(0);
    expect(current).toBe('');
  });

  it('does nothing in vanilla mode (loader disabled)', () => {
    ensureModloaderLaunchOptions(game({ modloader_enabled: false }));
    expect(sets).toHaveLength(0);
  });

  it('does nothing when the loader declares no launch options', () => {
    ensureModloaderLaunchOptions(game({ modloader_launch_options: '' }));
    expect(sets).toHaveLength(0);
  });

  it("preserves the user's own args when reapplying", () => {
    current = '%command% --foo';
    ensureModloaderLaunchOptions(game());
    expect(current).toBe('WINEDLLOVERRIDES="winhttp=n,b" %command% --foo');
  });
});

describe('addModloaderLaunchOptions merge', () => {
  it('sets the fragment as-is on an empty field', () => {
    addModloaderLaunchOptions(1, BEPINEX);
    expect(current).toBe(BEPINEX);
  });

  it('keeps user env vars before %command% and slots the loader prefix ahead', () => {
    current = 'MANGOHUD=1 %command%';
    addModloaderLaunchOptions(1, BEPINEX);
    expect(current).toBe('WINEDLLOVERRIDES="winhttp=n,b" MANGOHUD=1 %command%');
  });
});
