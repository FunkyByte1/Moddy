import os
import re
import decky


def find_steam_libraries() -> list[str]:
    """Parse Steam's libraryfolders.vdf to find all steamapps paths."""
    vdf_path = os.path.join(decky.DECKY_USER_HOME, ".steam", "steam", "steamapps", "libraryfolders.vdf")
    libraries = []
    try:
        with open(vdf_path, "r") as f:
            content = f.read()
        paths = re.findall(r'"path"\s+"([^"]+)"', content)
        for path in paths:
            steamapps = os.path.join(path, "steamapps")
            if os.path.isdir(steamapps):
                libraries.append(steamapps)
    except Exception as e:
        decky.logger.error(f"Failed to parse libraryfolders.vdf: {e}")
    return libraries


def get_proton_appdata_path(appid: int, relative_path: str) -> str:
    """
    Resolve a path inside a game's Proton prefix AppData/Roaming directory.
    e.g. get_proton_appdata_path(2379780, "Balatro/Mods") returns
    ~/.steam/steam/steamapps/compatdata/2379780/pfx/drive_c/users/steamuser/AppData/Roaming/Balatro/Mods
    """
    base = os.path.join(
        decky.DECKY_USER_HOME, ".steam", "steam", "steamapps",
        "compatdata", str(appid), "pfx", "drive_c", "users", "steamuser",
        "AppData", "Roaming"
    )
    return os.path.join(base, relative_path)


def find_game_install_dir(appid: int, libraries: list[str] | None = None) -> str | None:
    """Find the install directory for a game by its AppID. Pass `libraries` (the result
    of find_steam_libraries()) to reuse an already-parsed library list instead of
    re-reading libraryfolders.vdf — used when resolving many games in one pass."""
    for steamapps in (libraries if libraries is not None else find_steam_libraries()):
        manifest_path = os.path.join(steamapps, f"appmanifest_{appid}.acf")
        if os.path.isfile(manifest_path):
            try:
                with open(manifest_path, "r") as f:
                    content = f.read()
                match = re.search(r'"installdir"\s+"([^"]+)"', content)
                if match:
                    install_dir = os.path.join(steamapps, "common", match.group(1))
                    if os.path.isdir(install_dir):
                        return install_dir
            except Exception as e:
                decky.logger.error(f"Failed to parse manifest for {appid}: {e}")
    return None


def get_launch_options(appid: int) -> str:
    """Get the current launch options for a game."""
    localconfig_path = _find_localconfig()
    if not localconfig_path:
        return ""
    try:
        with open(localconfig_path, "r") as f:
            lines = f.readlines()
        return _find_launch_options_in_lines(lines, str(appid))
    except Exception as e:
        decky.logger.error(f"Failed to read launch options for {appid}: {e}")
    return ""


def set_launch_options(appid: int, options: str) -> bool:
    """Set the launch options for a game in localconfig.vdf."""
    localconfig_path = _find_localconfig()
    if not localconfig_path:
        decky.logger.error("Could not find localconfig.vdf")
        return False
    try:
        with open(localconfig_path, "r") as f:
            lines = f.readlines()

        new_lines = _set_launch_options_in_lines(lines, str(appid), options)
        if new_lines is None:
            decky.logger.error(f"Could not find appid {appid} section in localconfig.vdf")
            return False

        with open(localconfig_path, "w") as f:
            f.writelines(new_lines)

        decky.logger.info(f"Set launch options for {appid}: {options}")
        return True
    except Exception as e:
        decky.logger.error(f"Failed to set launch options for {appid}: {e}")
        return False


def get_compat_tool(appid: int) -> str:
    """The Steam Play compatibility tool that will run this game, read from config.vdf.

    Returns the per-app forced tool (Properties > Compatibility) if one is set, else the
    global "Steam Play for all other titles" default, else "" — which for a game with a
    native Linux build means it runs native. Mods built for the Windows build (BepInEx's
    winhttp.dll) only load under Proton, so "" is the signal that modding won't work yet.
    """
    config_path = _find_config_vdf()
    if not config_path:
        return ""
    try:
        with open(config_path, "r") as f:
            lines = f.readlines()
    except Exception as e:
        decky.logger.error(f"Failed to read compat tool for {appid}: {e}")
        return ""
    # Per-app override wins; fall back to the global default mapping (appid "0").
    return _find_compat_tool_in_lines(lines, str(appid)) or _find_compat_tool_in_lines(lines, "0")


def _find_compat_tool_in_lines(lines: list[str], appid: str) -> str:
    """Walk config.vdf tracking brace depth to find
    Software > Valve > Steam > CompatToolMapping > {appid} > "name" and return its value.
    """
    block_stack: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped == "{":
            continue
        if stripped == "}":
            if block_stack:
                block_stack.pop()
            continue
        key, value = _parse_vdf_line(stripped)
        if key is None:
            continue
        if value is None:
            block_stack.append(key)
        elif key.lower() == "name" and _is_in_compat_mapping(block_stack, appid):
            return value
    return ""


def _is_in_compat_mapping(block_stack: list[str], appid: str) -> bool:
    """True when the innermost block is the {appid} entry under
    ...Software > Valve > Steam > CompatToolMapping."""
    s = [b.lower() for b in block_stack]
    try:
        idx = s.index("compattoolmapping")
    except ValueError:
        return False
    pre = s[:idx]
    if not ("software" in pre and "valve" in pre and "steam" in pre):
        return False
    # The appid block must be CompatToolMapping's immediate child and the current innermost block.
    return idx == len(s) - 2 and s[idx + 1] == appid.lower()


def _find_launch_options_in_lines(lines: list[str], appid: str) -> str:
    """
    Walk the VDF line by line tracking brace depth to find the correct
    apps > appid block and return its LaunchOptions value.
    """
    # We need to find the block at path: Software > Valve > Steam > apps > {appid}
    # Track which named blocks we're inside
    depth = 0
    block_stack = []  # stack of block names at each depth
    in_target = False
    target_depth = None

    for line in lines:
        stripped = line.strip()

        if stripped == "{":
            depth += 1
            if block_stack and block_stack[-1] == appid and _is_in_apps_path(block_stack):
                in_target = True
                target_depth = depth
        elif stripped == "}":
            if in_target and depth == target_depth:
                in_target = False
                target_depth = None
            depth -= 1
            if block_stack:
                block_stack.pop()
        else:
            # Try to parse a key (block name or key/value pair)
            key, value = _parse_vdf_line(stripped)
            if key is not None:
                if value is None:
                    # This is a block name
                    block_stack.append(key)
                elif in_target and key.lower() == "launchoptions":
                    return value

    return ""


def _set_launch_options_in_lines(lines: list[str], appid: str, options: str) -> list[str] | None:
    """
    Walk the VDF line by line and update (or insert) the LaunchOptions
    value in the correct apps > appid block.
    Returns the modified lines, or None if the appid block was not found.
    """
    depth = 0
    block_stack = []
    in_target = False
    target_depth = None
    found = False
    result = []

    for i, line in enumerate(lines):
        stripped = line.strip()

        if stripped == "{":
            depth += 1
            if block_stack and block_stack[-1] == appid and _is_in_apps_path(block_stack):
                in_target = True
                target_depth = depth
            result.append(line)
        elif stripped == "}":
            if in_target and depth == target_depth:
                # Leaving the target block — if LaunchOptions wasn't found, insert it
                if not found:
                    indent = "\t" * depth
                    result.append(f'{indent}"LaunchOptions"\t\t"{options}"\n')
                    found = True
                in_target = False
                target_depth = None
            depth -= 1
            if block_stack:
                block_stack.pop()
            result.append(line)
        else:
            key, value = _parse_vdf_line(stripped)
            if key is not None:
                if value is None:
                    block_stack.append(key)
                elif in_target and key.lower() == "launchoptions":
                    # Replace this line
                    indent = line[: len(line) - len(line.lstrip())]
                    result.append(f'{indent}"LaunchOptions"\t\t"{options}"\n')
                    found = True
                    continue
            result.append(line)

    if not found and not in_target:
        # Never found the appid block at all
        return None

    return result


def _is_in_apps_path(block_stack: list[str]) -> bool:
    """Check if the block stack contains ...Software > Valve > Steam > apps > appid."""
    s = [b.lower() for b in block_stack]
    try:
        idx = s.index("apps")
        # Make sure software/valve/steam appear before apps
        pre = s[:idx]
        return "software" in pre and "valve" in pre and "steam" in pre
    except ValueError:
        return False


def _parse_vdf_line(stripped: str) -> tuple[str | None, str | None]:
    """
    Parse a VDF line. Returns:
      (key, None)   — block name (next line will be "{")
      (key, value)  — key/value pair
      (None, None)  — not a key line
    """
    # Match "key" "value"
    m = re.match(r'^"([^"]+)"\s+"([^"]*)"$', stripped)
    if m:
        return m.group(1), m.group(2)
    # Match "key" alone (block name)
    m = re.match(r'^"([^"]+)"\s*$', stripped)
    if m:
        return m.group(1), None
    return None, None


def _find_config_vdf() -> str | None:
    """The Steam-wide config.vdf (holds CompatToolMapping). Not per-user, unlike localconfig.vdf."""
    candidate = os.path.join(decky.DECKY_USER_HOME, ".steam", "steam", "config", "config.vdf")
    return candidate if os.path.isfile(candidate) else None


def _find_localconfig() -> str | None:
    """Find the localconfig.vdf file for the current Steam user."""
    userdata_path = os.path.join(decky.DECKY_USER_HOME, ".steam", "steam", "userdata")
    if not os.path.isdir(userdata_path):
        return None
    try:
        for entry in os.listdir(userdata_path):
            if entry == "0":  # anonymous
                continue
            candidate = os.path.join(userdata_path, entry, "config", "localconfig.vdf")
            if os.path.isfile(candidate):
                return candidate
    except Exception as e:
        decky.logger.error(f"Failed to find localconfig.vdf: {e}")
    return None