#!/bin/bash
DECK="deck@YOUR_DECK_IP"
PLUGIN_DIR="/home/deck/homebrew/plugins/decky-mod-manager"
TMP="/home/deck/decky-mod-manager_tmp"

# Build frontend
pnpm run build

# Copy files to tmp on Deck, then sudo move to plugin dir
ssh $DECK "mkdir -p $TMP/backend $TMP/dist"
scp main.py plugin.json package.json games.json "$DECK:$TMP/"
scp backend/games.py backend/steam.py backend/modloaders.py backend/mods.py backend/github.py "$DECK:$TMP/backend/"
scp dist/index.js dist/index.js.map "$DECK:$TMP/dist/"
ssh -t $DECK "sudo cp -r $TMP/* $PLUGIN_DIR/ && sudo chown -R deck:deck $PLUGIN_DIR && rm -rf $TMP"
ssh $DECK "sudo systemctl restart plugin_loader"
