import { GameStatus, ResetResult } from '../types';

// Pure logic behind Settings → "Reset all games": which games are worth resetting, and the
// one-line outcome toast. The actual loop (resetGame + removeModloaderLaunchOptions per game)
// lives in SettingsPage — launch options are SteamClient-only, so it must run frontend-side.

/** Games with anything Moddy-managed on disk: mods, a modloader, or a vanilla-mode snapshot
 *  (vanilla keeps everything on disk with the loader toggled off, so it still needs a reset). */
export function gamesNeedingReset(games: GameStatus[]): GameStatus[] {
  return games.filter(g =>
    g.installed && (g.installed_mods.length > 0 || g.modloader_installed || g.vanilla));
}

export interface PerGameReset {
  name: string;
  result: ResetResult | null;  // null = the reset call itself threw
}

/** Outcome toast body: totals, plus the names of any games whose reset failed. */
export function resetAllSummary(results: PerGameReset[]): string {
  const ok = results.filter(r => r.result?.ok).length;
  const mods = results.reduce((n, r) => n + (r.result?.mods_removed ?? 0), 0);
  const failed = results.filter(r => !r.result?.ok).map(r => r.name);
  const base = `Reset ${ok} game${ok === 1 ? '' : 's'} — ${mods} mod${mods === 1 ? '' : 's'} removed`;
  return failed.length
    ? `${base}; failed for ${failed.join(', ')} — check the log`
    : base;
}
