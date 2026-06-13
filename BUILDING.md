# Building Moddy from source

This package is free software licensed under the **GNU GPL v3.0 or later** (see
`LICENSE`). The complete Corresponding Source is included in this archive so you
can study, modify, and rebuild it.

## What's compiled

The only build artifact shipped here is `dist/index.js`, the bundled frontend.
It is produced from the TypeScript/React sources in `src/`. The Python backend
(`main.py`, `backend/*.py`) is interpreted and already in source form.

## Rebuilding the frontend

Requirements: [Node.js](https://nodejs.org) 20+ and [pnpm](https://pnpm.io) 9+.

```bash
pnpm install --frozen-lockfile   # uses the bundled pnpm-lock.yaml
pnpm run build                   # runs rollup -c, regenerates dist/index.js
```

The build configuration lives in `rollup.config.js` and `tsconfig.json`.

## Installing into Decky Loader

This folder is already laid out as a Decky plugin. To run it, copy the whole
`moddy/` folder into `~/homebrew/plugins/` on your Steam Deck and restart the
plugin loader, or install the zip directly via Decky's "Install from URL".
