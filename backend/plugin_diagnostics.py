import decky
import sys
import os
import registry
import steam


async def export_logs() -> str | None:
    """Bundle Moddy's logs, the installed.json store (+ its .bak and any quarantined
    .corrupt-* copies), and a small system-info file into one zip the user can attach
    to a bug report. The store carries no secrets and is the first artifact needed to
    debug any install/toggle/uninstall report; a quarantined copy is the whole story
    for a "my library vanished" report. Writes to the Deck's Desktop (easy to find and
    drag into a browser upload), falling back to the user's home, and returns the full
    path. Deliberately excludes settings.json so the Nexus API key never leaves the
    device."""
    import glob
    import time
    import zipfile
    try:
        log_dir = decky.DECKY_PLUGIN_LOG_DIR
        home = getattr(decky, "DECKY_USER_HOME", None) or decky.HOME
        desktop = os.path.join(home, "Desktop")
        dest_dir = desktop if os.path.isdir(desktop) else home
        ts = time.strftime("%Y%m%d-%H%M%S")
        dest = os.path.join(dest_dir, f"moddy-logs-{ts}.zip")

        # System info, so reports carry version/env without us having to ask for it.
        info = [
            f"Moddy {getattr(decky, 'DECKY_PLUGIN_VERSION', '?')}",
            f"Decky {getattr(decky, 'DECKY_VERSION', '?')}",
            f"Platform: {sys.platform}",
            f"Exported: {ts}",
            "",
            "Supported games:",
        ]
        for game in registry.SUPPORTED_GAMES:
            install_dir = steam.find_game_install_dir(game.appid)
            state = "installed" if install_dir else "not installed"
            info.append(f" - {game.name} ({game.appid}): {state}")

        log_files = [p for p in glob.glob(os.path.join(log_dir, "*")) if os.path.isfile(p)]
        store = os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "installed.json")
        store_files = [p for p in (store, store + ".bak", *sorted(glob.glob(store + ".corrupt-*")))
                       if os.path.isfile(p)]
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("moddy-info.txt", "\n".join(info) + "\n")
            for path in log_files:
                zf.write(path, arcname=os.path.join("logs", os.path.basename(path)))
            for path in store_files:
                zf.write(path, arcname=os.path.join("store", os.path.basename(path)))

        decky.logger.info(f"Exported {len(log_files)} log file(s) to {dest}")
        return dest
    except Exception as e:
        decky.logger.error(f"Log export failed: {e}")
        return None
