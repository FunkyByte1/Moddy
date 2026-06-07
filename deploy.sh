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