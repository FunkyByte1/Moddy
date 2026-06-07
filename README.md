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

- **Slime Rancher 2** — MelonLoader, Starlight, SR2 Gyro Aim

More games coming soon.

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

ssh $DECK "mkdir -p $TMP/backend $TMP/dist"
scp main.py plugin.json package.json registry.json "$DECK:$TMP/"
scp backend/registry.py backend/steam.py backend/modloaders.py backend/mods.py backend/github.py backend/utils.py "$DECK:$TMP/backend/"
scp dist/index.js dist/index.js.map "$DECK:$TMP/dist/"
ssh -t $DECK "sudo cp -r $TMP/* $PLUGIN_DIR/ && sudo chown -R deck:deck $PLUGIN_DIR && rm -rf $TMP"
ssh $DECK "sudo systemctl restart plugin_loader"
```

Then `chmod +x deploy.sh && ./deploy.sh`.

### Adding a Game

Edit `registry.json` to add a new game entry with its mod loader and mods. See existing entries for the v2 schema format.

## License

Copyright (C) 2026 FunkyByte1

This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the [GNU General Public License](LICENSE) for more details.