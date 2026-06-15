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

If it's empty, paste it in yourself. (You can verify REFramework is working by launching the game —
its overlay appears, openable with the **Insert** key, or hold the **Steam** button and use the right
trackpad as a mouse.)

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

### Known limitations

- **`.pak`-only mods and uninstalling:** Moddy numbers `.pak` mods in install order. Uninstalling a
  `.pak` mod that has *other* `.pak` mods installed after it can leave a numbering gap; if a later
  `.pak` mod stops loading, reinstall it. Loose-file (`natives/`) mods aren't affected.
