# Contributing to Moddy

Thanks for your interest in improving Moddy. This covers the local dev setup, deploying a build to a
Steam Deck, and how games get added.

## Requirements

- Node.js v20+
- pnpm v9 (`npm i -g pnpm@9`)
- A Steam Deck (or SteamOS VM) running [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader)

## Build

```bash
pnpm i
pnpm run build
```

The Python backend has a pure-stdlib `unittest` suite (no pytest dependency):

```bash
cd tests && python3 -m unittest discover -p "test_*.py"
```

## Deploy to Steam Deck

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
ssh $DECK "sudo systemctl stop plugin_loader"
ssh $DECK "rm -f $PLUGIN_DIR/registry.json && cp -r $TMP/* $PLUGIN_DIR/ && rm -rf $TMP"
ssh $DECK "sudo systemctl start plugin_loader"
```

Stop the loader **before** copying: writing into the live plugin directory fires Decky's file
watcher into a mid-copy reload, and a reload race can wedge a plugin sandbox process inside
Decky's socket read loop (runaway CPU/memory that survives the service restart).

Then `chmod +x deploy.sh && ./deploy.sh`.

For passwordless deploys, take ownership of the plugin dir once
(`sudo chown -R deck:deck /home/deck/homebrew/plugins/moddy`) and whitelist the restart command via
sudoers (`echo 'deck ALL=(ALL) NOPASSWD: /usr/bin/systemctl stop plugin_loader, /usr/bin/systemctl start plugin_loader, /usr/bin/systemctl restart plugin_loader' | sudo tee /etc/sudoers.d/zz-moddy-deploy && sudo chmod 0440 /etc/sudoers.d/zz-moddy-deploy`; the `zz-` name matters — sudoers is last-match-wins and SteamOS's own `/etc/sudoers.d/wheel` would otherwise override the NOPASSWD entry).

## Adding a game

How much work this is depends entirely on whether the game fits something Moddy already does.

**Pure data (no Python).** If the game reuses a download source, mod loader, and install layout Moddy
already supports, you only add JSON under `registry/games/` (id, Steam appid, mods dir, mod loader
ids, curated mod list) — copy the closest existing entry for the schema. Steam Workshop games are the
simplest case (see `registry/games/brotato.json`): little more than the appid and the shared
`steamworkshop` loader. If the game needs a mod loader that already has a definition under
`registry/modloaders/`, just reference its id.

**Needs backend code.** A game that introduces a **new download source/venue** (e.g. ficsit.app), a
**new mod loader integration** (e.g. UE4SS), or a **new install/extraction layout** (how a downloaded
archive maps onto the game's folders) requires Python in `backend/` plus tests under `tests/`. The
data-driven path covers reuse; genuinely new mechanics don't.
