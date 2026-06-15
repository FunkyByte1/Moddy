# Modding Resident Evil 4 (remake) with Moddy

RE4 mods come from [Nexus Mods](https://www.nexusmods.com/residentevil42023) and load through
**REFramework**, a mod loader Moddy installs for you. Once it's set up, installing a mod is the
same one-click flow as any other game.

> **Two things you need first:**
> - A **Nexus Premium** account + API key — see [Adding your Nexus Mods API key](nexus-api-key.md).
>   (Free accounts can browse but not download; that's a Nexus limitation.)
> - **Resident Evil 4** installed on your Steam Deck.

## 1. Install the REFramework loader

In Moddy, open **Resident Evil 4** and install the **REFramework** mod loader (same place you'd
install MelonLoader/BepInEx for other games). Moddy will:

- drop `dinput8.dll` into the game folder,
- turn on REFramework's **Loose File Loader** (this is what makes mods actually load — current RE4
  builds don't read loose mod files on their own), and
- set the Steam launch option `WINEDLLOVERRIDES="dinput8=n,b" %command%`.

**Confirm the launch option stuck.** Steam sometimes ignores launch-option changes made while it's
running. Open **RE4 → Properties → Launch Options** and check it reads exactly:

```
WINEDLLOVERRIDES="dinput8=n,b" %command%
```

If it's empty, paste it in yourself.

**The REFramework overlay starts closed.** Moddy configures REFramework to start with its menu
**closed** (otherwise it pops open on every launch and you'd have to dismiss it). The menu toggle is
the keyboard **Insert** key — which a controller can't press directly, so on the Deck **bind a button
to Insert**: Steam → **RE4 → Controller Settings**, add a **keyboard `Insert`** command to a spare
button (a back paddle like L4/R4, or a chord such as **Steam + ◻**). Pressing it opens/closes the
overlay; once open, hold the **Steam** button and use the right trackpad as a mouse to click around.
(REFramework remembers the menu's last state, so if you leave it open on exit it'll reopen next launch.)

## 2. Install mods

Open the **Browse** tab, search Nexus, and install. Moddy handles both RE4 mod formats automatically:

- **Loose-file mods** (most cosmetics — skins, models, textures): extracted into the game's
  `natives/` folder for REFramework's loose loader.
- **`.pak` mods**: slotted in as the next `re_chunk_000.pak.patch_NNN.pak` so they override the base game.

Enable/disable and uninstall work from the **Installed** tab like any other game.

## Troubleshooting

- **A mod installed but doesn't show up in-game.** Most outfit/weapon mods replace a *specific*
  costume or weapon slot — make sure you're looking at the right one. If nothing loads at all, check
  that REFramework is installed and the launch option above is set.
- **The game crashes on launch.** First, rule out corrupted game files: **RE4 → Properties →
  Installed Files → Verify integrity of game files** (an interrupted download can corrupt the base
  game, which crashes it regardless of mods). If vanilla launches but modded doesn't, disable mods
  one at a time to find the culprit.
- **"Install" succeeds but the mod never appears in Installed.** If you're testing dev builds, make
  sure Decky fully reloaded the plugin after an update before installing — otherwise a stale install
  record can block things. A clean reinstall fixes it.
- **Free Nexus account.** Browsing works, but downloads need Premium (a Nexus API limitation).

### `.pak` mod load order

`.pak` mods override each other by load order, and Moddy loads them **in the order you installed
them — the most recently installed wins.** So if a mod's page says *"install this after other
animation / melee / combat mods,"* just install it **last** and it'll take priority.

Uninstalling a `.pak` mod automatically renumbers the rest so they stay contiguous and keep loading
(and keep their relative priority) — no gaps, nothing to reinstall. There's no manual reorder yet, so
to change which of two conflicting `.pak` mods wins, reinstall the one that should win last.
