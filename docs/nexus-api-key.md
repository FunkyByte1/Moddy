# Adding your Nexus Mods API key

Moddy installs Nexus mods through **your own** Nexus account, so you add a personal
API key once. (GitHub, Thunderstore, and Balatro mods don't need this — only Nexus.)

> **Heads up — Nexus Premium required for downloads.** Nexus only returns a direct
> download link through its API to **Premium** members. With a free account you can
> *browse* Nexus mods in Moddy but not install them. That's a Nexus limitation, not
> Moddy's.

## 1. Get your key

1. Sign in at <https://www.nexusmods.com>.
2. Go to **Account settings → API Keys** (direct link: <https://www.nexusmods.com/users/myaccount?tab=api>).
3. Under **Personal API Key**, click **Generate** (or copy your existing one).

Keep it handy — it's a long random string.

## 2. Add it to Moddy

Because the key is long, **pasting** is much easier than typing it on the Steam Deck keyboard.

### Easiest: Desktop Mode

1. Switch to **Desktop Mode**.
2. Open the **Decky** menu (the plug 🔌 icon) → **Moddy**.
3. Under **Settings**, **paste** your key into the **Nexus Mods API key** field.

It saves automatically. Switch back to Game Mode and open a supported game's **Browse** tab — you'll see Nexus mods.

### Game Mode

Same place — **Decky → Moddy → Settings** — just type the key with the on-screen keyboard.

<details>
<summary>Advanced: set it over SSH</summary>

```bash
mkdir -p ~/homebrew/settings/moddy
cat > ~/homebrew/settings/moddy/settings.json <<'EOF'
{ "nexus_api_key": "PASTE_YOUR_KEY_HERE" }
EOF
sudo systemctl restart plugin_loader
```

The folder is lowercase `moddy`; the key is read on startup.
</details>

## Notes

- Your key is stored **only on your Steam Deck** and is sent **only to Nexus Mods** — never to any other server.
- You can revoke or regenerate the key anytime from the same Nexus API Keys page; just paste the new one into Moddy.
