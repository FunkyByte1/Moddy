# Moddy

A [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader) plugin for one-click mod installation and management on Steam Deck — directly in Game Mode.

## Features

- Browse and install mods without leaving Game Mode
- Mod loader installation and management (MelonLoader, BepInEx, Lovely)
- Version selection with rollback support
- Dependency resolution and cascade disable/uninstall
- Update checking for mods and mod loader
- Controller-native UI with d-pad navigation

## Supported Games
### Currently Supported:

- Slime Rancher 2
- Risk of Rain 2
- Balatro

### Planned:
- Stardew Valley
- Resident Evil 4
- Haste
- and more :)


## Mod Sources

Mods and modloaders are downloaded directly from their original publishers:

- **GitHub Releases** — for projects that publish built assets there (e.g. MelonLoader, Starlight, R2API).
- **[Thunderstore](https://thunderstore.io)** — for the wider Risk of Rain 2 / BepInEx mod ecosystem, accessed via Thunderstore's public API the same way [r2modman](https://github.com/ebkr/r2modmanPlus), [Thunderstore Mod Manager](https://www.overwolf.com/app/Thunderstore-Thunderstore_Mod_Manager), and [Gale](https://github.com/Kesomannen/gale) do. Moddy does not host, redistribute, or modify any mod content — it links to and downloads from the original sources, and each mod's license is set by its author.
- **[Balatro Mod Index](https://github.com/skyline69/balatro-mod-index)** — for Balatro mods, Moddy reads the community mod index maintained by the [Balatro Mod Manager](https://github.com/skyline69/balatro-mod-manager) project (© 2025 Efe, MIT-licensed). Moddy reads the index directly from its public GitHub repository to list mods, then downloads each mod from its own original source. Huge thanks to that project and its contributors for curating the index.
- **[Nexus Mods](https://www.nexusmods.com)** — accessed through the official Nexus Mods API using **your own personal API key** (the same way [Vortex](https://www.nexusmods.com/about/vortex/) does). Moddy does not host or redistribute any mod content; it searches via the public API and downloads each file from Nexus's own CDN. **This version supports downloads for Nexus Premium accounts only** — free accounts can browse, but Nexus's API only returns a direct download link to Premium members. Your API key is stored only on your device and is sent only to Nexus.

### Setting up your Nexus Mods API key

To browse or install Nexus mods you need a (free) Nexus account and a **personal API key**:

1. Sign in at [nexusmods.com](https://www.nexusmods.com), then open **Account settings → [API Keys](https://www.nexusmods.com/users/myaccount?tab=api)**.
2. Under **Personal API Key**, click **Generate** (or copy your existing one).

Then add the key to Moddy. The key is ~30 random characters, so pasting is far easier than typing it on the Game Mode keyboard — pick whichever is convenient:

- **Desktop Mode (easiest):** switch to Desktop Mode, open the Decky panel → **Moddy → Settings**, and **paste** your key into the *Nexus Mods API key* field (real keyboard + clipboard).
- **Game Mode:** open the Decky panel → **Moddy → Settings** and type the key into the *Nexus Mods API key* field with the on-screen keyboard.
- **Advanced (SSH / file):** edit `~/homebrew/settings/moddy/settings.json` on the deck and set `nexus_api_key`, then restart Decky so it's picked up:
  ```bash
  mkdir -p ~/homebrew/settings/moddy
  cat > ~/homebrew/settings/moddy/settings.json <<'EOF'
  { "nexus_api_key": "PASTE_YOUR_KEY_HERE" }
  EOF
  sudo systemctl restart plugin_loader
  ```
  (The folder name is lowercase `moddy`; the file is read on startup.)

For a shareable step-by-step (handy for testers), see **[docs/nexus-api-key.md](docs/nexus-api-key.md)**.

## Acknowledgements

- The **Balatro Mod Index** (catalog data) is by the [Balatro Mod Manager](https://github.com/skyline69/balatro-mod-manager) project, © 2025 Efe, licensed under the [MIT License](https://github.com/skyline69/balatro-mod-index/blob/main/LICENSE). Moddy uses only the index data — none of that project's source code.
- Balatro modding is powered by the [Lovely injector](https://github.com/ethangreen-dev/lovely-injector) and [Steamodded](https://github.com/Steamodded/smods), installed from their official releases.

## Disclaimer

Mods installed through Moddy are **third-party software not authored, audited, or endorsed by this project**. They are downloaded from their original publishers and run with the same privileges as your user account — they are not sandboxed or isolated from the rest of your system.

Use Moddy and any mods you install **at your own risk**. The author accepts no responsibility or liability for any damage arising from their use, including but not limited to corrupted or lost save data, broken or unbootable game installations, system instability, exposure to malicious code, or **bans from anti-cheat systems or online services**. Modifying a game may violate its terms of service, and online/multiplayer titles in particular may detect mods and penalize your account.

Review the source and author before installing anything you don't recognize. Moddy is provided **"AS IS"**, without warranty of any kind. See the [License](#license) below for the full warranty disclaimer.

## AI Disclosure

Yes, a large portion of this was made with AI/vibe-coding. I'm a single person working on this in the small amounts of free time I get, and AI is the tool that lets me ship at all.

I'm open to someone de-slopping the project and submitting PRs. If that happens, I'll use a lot less AI going forward. But for now, it's what I have, and I'd rather be upfront about it than pretend otherwise.

## Development

### Requirements

- Node.js v16.14+
- pnpm v9 (`npm i -g pnpm@9`)
- A Steam Deck (or SteamOS VM) running [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader)

### Build

```bash
pnpm i
pnpm run build
```

### Deploy to Steam Deck

Create a `deploy.sh` in the project root (gitignored — do not commit your IP address):

```bash
#!/bin/bash
DECK="deck@YOUR_DECK_IP"
PLUGIN_DIR="/home/deck/homebrew/plugins/moddy"
TMP="/home/deck/moddy_tmp"

pnpm run build

ssh $DECK "mkdir -p $TMP/backend $TMP/dist && rm -rf $TMP/registry"
scp main.py plugin.json package.json "$DECK:$TMP/"
scp -r registry "$DECK:$TMP/"
scp backend/*.py "$DECK:$TMP/backend/"
scp dist/index.js dist/index.js.map "$DECK:$TMP/dist/"
ssh $DECK "rm -f $PLUGIN_DIR/registry.json && cp -r $TMP/* $PLUGIN_DIR/ && rm -rf $TMP"
ssh $DECK "sudo systemctl restart plugin_loader"
```

Then `chmod +x deploy.sh && ./deploy.sh`.

For passwordless deploys, take ownership of the plugin dir once (`sudo chown -R deck:deck /home/deck/homebrew/plugins/moddy`) and whitelist the restart command via sudoers (`echo 'deck ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart plugin_loader' | sudo tee /etc/sudoers.d/moddy-deploy && sudo chmod 0440 /etc/sudoers.d/moddy-deploy`).

### Adding a Game

Drop a JSON file into `registry/games/` describing the game (id, Steam appid, mods dir, mod loader ids, and curated mod list). If the game uses a new mod loader, also add its definition under `registry/modloaders/`. No Python edits required. See existing entries for the schema.

## License

Copyright (C) 2026 FunkyByte1

This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the [GNU General Public License](LICENSE) for more details.