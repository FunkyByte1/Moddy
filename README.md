# Moddy

A [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader) plugin for one-click mod installation and management on Steam Deck — directly in Game Mode.

## Features

- Browse and install mods without leaving Game Mode
- MelonLoader installation and management
- Version selection with rollback support
- Dependency resolution and cascade disable/uninstall
- Update checking for mods and mod loader
- Controller-native UI with d-pad navigation

## Supported Games
### Currently Supported:

- Slime Rancher 2
- Risk of Rain 2

### Planned:
- Stardew Valley
- Resident Evil 4
- Balatro
- Haste
- and more :)


## Mod Sources

Mods and modloaders are downloaded directly from their original publishers:

- **GitHub Releases** — for projects that publish built assets there (e.g. MelonLoader, Starlight, R2API).
- **[Thunderstore](https://thunderstore.io)** — for the wider Risk of Rain 2 / BepInEx mod ecosystem, accessed via Thunderstore's public API the same way [r2modman](https://github.com/ebkr/r2modmanPlus), [Thunderstore Mod Manager](https://www.overwolf.com/app/Thunderstore-Thunderstore_Mod_Manager), and [Gale](https://github.com/Kesomannen/gale) do. Moddy does not host, redistribute, or modify any mod content — it links to and downloads from the original sources, and each mod's license is set by its author.

Mods installed through Moddy are third-party software not authored or audited by this project. Review the source and author before installing anything you don't recognize.

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
scp backend/registry.py backend/steam.py backend/modloaders.py backend/mods.py backend/github.py backend/utils.py "$DECK:$TMP/backend/"
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