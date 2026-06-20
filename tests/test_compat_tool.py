"""Unit tests for steam.get_compat_tool — the config.vdf reader that tells the UI whether a
game (e.g. Enter the Gungeon, which has a native Linux build) will run under Proton. Mods built
for the Windows build only load under Proton, so an empty result is the "modding won't work yet"
signal that drives the force-Proton prompt.

Covers the pure line walker (path-scoped to Software>Valve>Steam>CompatToolMapping>{appid}>name,
per-app override beating the global "0" default) and the file wrapper against a temp config.vdf.
"""
import os
import tempfile
import unittest

from _harness import reset_store  # noqa: F401  (imported for its sys.path / fake-decky side effects)
import decky
import steam


def _config_vdf(per_app: dict | None = None, default: str | None = None) -> str:
    """A minimal config.vdf with a CompatToolMapping. `per_app` maps appid -> tool name;
    `default` is the global "Steam Play for all other titles" tool (the "0" entry)."""
    entries = dict(per_app or {})
    if default is not None:
        entries["0"] = default
    blocks = ""
    for appid, name in entries.items():
        blocks += (
            f'\t\t\t\t\t"{appid}"\n\t\t\t\t\t{{\n'
            f'\t\t\t\t\t\t"name"\t\t"{name}"\n'
            f'\t\t\t\t\t\t"config"\t\t""\n'
            f'\t\t\t\t\t\t"priority"\t\t"250"\n'
            f'\t\t\t\t\t}}\n'
        )
    return (
        '"InstallConfigStore"\n{\n\t"Software"\n\t{\n\t\t"Valve"\n\t\t{\n\t\t\t"Steam"\n\t\t\t{\n'
        '\t\t\t\t"CompatToolMapping"\n\t\t\t\t{\n'
        f'{blocks}'
        '\t\t\t\t}\n\t\t\t}\n\t\t}\n\t}\n}\n'
    )


class FindCompatToolInLinesTest(unittest.TestCase):
    def _find(self, vdf: str, appid: str) -> str:
        return steam._find_compat_tool_in_lines(vdf.splitlines(keepends=True), appid)

    def test_per_app_mapping(self):
        vdf = _config_vdf(per_app={"311690": "proton_experimental"})
        self.assertEqual(self._find(vdf, "311690"), "proton_experimental")

    def test_missing_appid_returns_empty(self):
        vdf = _config_vdf(per_app={"311690": "proton_experimental"})
        self.assertEqual(self._find(vdf, "632360"), "")

    def test_global_default_entry(self):
        vdf = _config_vdf(default="proton_9")
        self.assertEqual(self._find(vdf, "0"), "proton_9")

    def test_name_key_outside_mapping_is_ignored(self):
        # A "name" key living elsewhere in config.vdf must not be mistaken for a compat tool.
        vdf = (
            '"InstallConfigStore"\n{\n\t"Software"\n\t{\n\t\t"Valve"\n\t\t{\n\t\t\t"Steam"\n\t\t\t{\n'
            '\t\t\t\t"SomethingElse"\n\t\t\t\t{\n\t\t\t\t\t"311690"\n\t\t\t\t\t{\n'
            '\t\t\t\t\t\t"name"\t\t"not_a_compat_tool"\n\t\t\t\t\t}\n\t\t\t\t}\n'
            '\t\t\t}\n\t\t}\n\t}\n}\n'
        )
        self.assertEqual(self._find(vdf, "311690"), "")


class GetCompatToolTest(unittest.TestCase):
    def setUp(self):
        # Isolate DECKY_USER_HOME so we own ~/.steam/steam/config/config.vdf for this test.
        decky.DECKY_USER_HOME = tempfile.mkdtemp(prefix="moddy-home-compat-")
        self._config_dir = os.path.join(decky.DECKY_USER_HOME, ".steam", "steam", "config")
        os.makedirs(self._config_dir, exist_ok=True)

    def _write(self, vdf: str) -> None:
        with open(os.path.join(self._config_dir, "config.vdf"), "w") as f:
            f.write(vdf)

    def test_per_app_overrides_global_default(self):
        self._write(_config_vdf(per_app={"311690": "proton_experimental"}, default="proton_9"))
        self.assertEqual(steam.get_compat_tool(311690), "proton_experimental")

    def test_falls_back_to_global_default(self):
        self._write(_config_vdf(per_app={"632360": "proton_8"}, default="proton_9"))
        self.assertEqual(steam.get_compat_tool(311690), "proton_9")

    def test_no_mapping_means_native(self):
        # Native Linux game, no per-app tool, no global default -> "" (mods won't load yet).
        self._write(_config_vdf(per_app={"632360": "proton_8"}))
        self.assertEqual(steam.get_compat_tool(311690), "")

    def test_missing_config_file_returns_empty(self):
        # Fresh home with no config.vdf at all.
        decky.DECKY_USER_HOME = tempfile.mkdtemp(prefix="moddy-home-empty-")
        self.assertEqual(steam.get_compat_tool(311690), "")


if __name__ == "__main__":
    unittest.main()
