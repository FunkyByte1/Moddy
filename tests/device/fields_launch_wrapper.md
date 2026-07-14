> ⚠️ **GATED / ON HOLD (2026-07-07).** Fields of Mistria is disabled in the registry
> (`enabled: false`) because MOMI can't mod the current game build — it dropped `data.win`
> for a packed `assets.zip`, and MOMI's new-engine support is beta-only with broken Linux/Deck
> game-detection (no path override, misses SD-card libraries, `data.win`-gated cwd fallback,
> exits 0 on failure). See `registry/games/fields-of-mistria.json` → `disabled_reason` and the
> upstream issue in `tmp/momi-issue-draft.md`. This test plan (and the launch wrapper it targets)
> is kept for when MOMI is fixed and Fields is re-enabled — **do not run it until then.**

# Device test — Fields of Mistria apply-on-Play launch wrapper

Manual device test (Steam Deck, Desktop Mode + konsole). The MOMI CLI run and the
Steam launch path can't be exercised in unit tests, so this is the acceptance gate
for the launch wrapper. Run every section; check the box only on the stated result.

## Wrapper contract under test

Moddy sets Fields' Steam launch option to `"<wrapper>" %command%`. On Play the wrapper:

1. If the **sentinel** file exists (mods staged but not baked):
   - run the MOMI CLI (`cwd = game dir`, `EXIT_ON_COMPLETE=true`) to rebuild `data.win`;
   - **on exit 0** → delete the sentinel, then `exec "$@"` (launch the game);
   - **on non-zero exit or if killed** → `exit 1`, **do NOT** `exec` — the game must not launch.
2. If no sentinel → skip the bake and `exec "$@"` immediately (zero delay).
3. In vanilla mode → skip the bake (game is meant to be pristine).

Design decision (locked): a failed or cancelled apply must **not** launch the game. Pressing B
means "don't launch"; a broken-mod failure must be loud (game doesn't start), never a silent
modless launch.

## Observation cheat-sheet

```sh
# --- paths (this Deck: games live on the SD card) ---
STEAMLIB="/run/media/deck/5586441b-81af-4df4-a209-87c7778c451e/steamapps"
GAMEDIR="$STEAMLIB/common/Fields of Mistria"

RUNTIME="$HOME/homebrew/data/moddy/mergetools/momi"   # DECKY_PLUGIN_RUNTIME_DIR/mergetools/momi (dir is lowercase 'moddy')
MOMI="$RUNTIME/ModsOfMistriaInstaller-cli-linux"
SENTINEL="$RUNTIME/pending-2142790"                    # exact name confirmed once wrapper is built
APPLYLOG="$RUNTIME/apply.log"

# --- state snapshots ---
alias winhash='md5sum "$GAMEDIR/data.win"'                       # changes iff data.win rebuilt
alias baks='ls -la "$GAMEDIR"/data.bak.win "$GAMEDIR"/*.bak.json 2>/dev/null'  # MOMI's pristine backup
alias sentinel='ls -la "$SENTINEL" 2>/dev/null && echo PENDING || echo clean'
alias mods='ls "$GAMEDIR/mods"'                                  # staged mod folders
plog() { tail -n 40 "$APPLYLOG"; }                              # wrapper/MOMI log

# --- decky backend log (plugin side) ---
DECKYLOG="$HOME/homebrew/logs/moddy/plugin.log"
```

Record a baseline before starting: `winhash; baks; sentinel; mods`.

---

## 1. Install & wiring
- [ ] Install the MOMI loader from the Mod Loader tab. Confirm `$MOMI` exists and is executable
      (`test -x "$MOMI" && echo ok`), and the loader shows a recorded version.
- [ ] Open Fields → Properties → Launch Options in Steam. Confirm it reads
      `"<...>/moddy-apply" %command%` (or the wrapper name Moddy chose) — **not** empty, not clobbered.

## 2. Happy path — apply on Play
- [ ] Install one asset mod (e.g. a cosmetic/texture mod) from Browse. `sentinel` → **PENDING**;
      `mods` shows its folder; `winhash` **unchanged** (staged only, not baked yet).
- [ ] Press **Play**. "Launching…" lingers for the bake, then the game starts.
- [ ] In-game: the mod is visibly active.
- [ ] After exit: `sentinel` → **clean**, `winhash` **changed** vs. step-2 baseline, `plog` shows a
      successful MOMI run (exit 0).

## 3. No-op launch — nothing pending
- [ ] With `sentinel` **clean**, press **Play**. Game launches with **no** perceptible bake delay.
- [ ] `winhash` unchanged; `plog` shows the wrapper skipped MOMI (no new run).

## 4. Cancel mid-bake (press B)  ← the reason for this test
- [ ] Install another mod so `sentinel` → **PENDING**. Note `winhash`.
- [ ] Press **Play**, and while "Launching…" is still showing (during the bake), press **B** to cancel.
- [ ] **Game does NOT launch.**
- [ ] `sentinel` still **PENDING** (not cleared by an interrupted apply).
- [ ] Press **Play** again, let it finish this time. Game launches, mod active, `sentinel` → **clean**.
      → proves an interrupted bake is retried, never silently "applied".

## 5. Failed apply — broken mod must NOT launch modless
- [ ] Force a MOMI failure. Easiest: stage a deliberately malformed mod folder, e.g.
      `mkdir -p "$GAMEDIR/mods/_BADTEST" && echo 'not json' > "$GAMEDIR/mods/_BADTEST/manifest.json"`,
      then trigger a stage so `sentinel` → **PENDING** (install any real mod, or `touch "$SENTINEL"`).
- [ ] Press **Play**. Bake runs, MOMI errors out.
- [ ] **Game does NOT launch** (no fallback to a modless/vanilla start).
- [ ] `sentinel` still **PENDING**; `plog` shows the non-zero MOMI exit; the Apply banner is still present in Moddy.
- [ ] Clean up: `rm -rf "$GAMEDIR/mods/_BADTEST"`, then Apply from Moddy → succeeds, `sentinel` → clean.

## 6. MOMI write-atomicity stress  ← decides whether Case B is *provably* safe
Verifies MOMI can be hard-killed mid-write and still recover — i.e. it writes `data.win`/its backup
via temp-then-rename, so there is no unrecoverable window. Runs MOMI directly, independent of Steam.
- [ ] Ensure at least one mod is staged in `$GAMEDIR/mods`. Snapshot `baks` and `winhash`.
- [ ] Hard-kill MOMI mid-run, repeatedly:
      ```sh
      cd "$GAMEDIR"
      for i in $(seq 1 20); do
        EXIT_ON_COMPLETE=true "$MOMI" >/dev/null 2>&1 &
        pid=$!; sleep 0.25; kill -9 "$pid" 2>/dev/null; wait "$pid" 2>/dev/null
      done
      ```
- [ ] Now run one clean apply: `cd "$GAMEDIR" && EXIT_ON_COMPLETE=true "$MOMI"; echo "exit=$?"`.
      Expect `exit=0`.
- [ ] `baks` still shows a valid `data.bak.win` (pristine backup survived the kills).
- [ ] Launch the game from Steam → loads normally with the mod active (no corruption).
      → **If this ever fails to recover, MOMI writes in place** and the wrapper must restore from a
      Moddy-owned pristine copy before each bake. Note the outcome either way.

## 7. Vanilla mode skips the bake
- [ ] Enter Vanilla Mode in Moddy. Confirm `data.win` is restored to pristine
      (`winhash` matches a known no-mods hash; mods toggled off on disk).
- [ ] Press **Play**. Wrapper does **not** run a bake; game launches vanilla. `plog` shows the skip.
- [ ] Leave Vanilla Mode → `sentinel` becomes **PENDING** (mods re-staged); next Play re-bakes.

## 8. Game-update / stale handling
- [ ] With mods applied, trigger a Steam update of Fields (or simulate: bump `buildid` in
      `steamapps/appmanifest_2142790.acf` and touch `data.win`). Moddy should surface **stale**.
- [ ] Stage/Apply (or Play). Confirm from `plog` that Moddy **deletes MOMI's `*.bak.*` first**
      (so the update isn't reverted), then rebuilds. `baks` shows a fresh backup post-update.
- [ ] Game launches on the updated build with mods active — the update is **not** rolled back.

## 9. Launch-option persistence / self-heal
- [ ] Clear Fields' launch options manually in Steam, then reopen the Mod Page in Moddy.
- [ ] Confirm Moddy reapplies the wrapper launch option (same self-heal as the modloader launch option).
- [ ] Press **Play** → wrapper still runs (bake happens if pending).

---

## Result

| # | Test | Pass |
|---|------|------|
| 1 | Install & wiring | ☐ |
| 2 | Apply on Play | ☐ |
| 3 | No-op launch | ☐ |
| 4 | Cancel mid-bake (B) | ☐ |
| 5 | Failed apply — no modless launch | ☐ |
| 6 | MOMI write-atomicity stress | ☐ |
| 7 | Vanilla skips bake | ☐ |
| 8 | Game-update / stale | ☐ |
| 9 | Launch-option self-heal | ☐ |

Notes / anomalies:
