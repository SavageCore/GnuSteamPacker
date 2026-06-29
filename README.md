# GnuSteamPacker

A Linux-native GUI for downloading, cleaning, and packaging Steam games for archival and sharing. Spiritual port of [SuperSteamPacker](https://github.com/Masquerade64/SuperSteamPacker) built with Python, GTK4, and libadwaita.

Features:
- Search Steam for games by name or AppID
- Download via SteamCMD
- Generate clean ACF manifest files
- Compress to a single `.7z` archive
- Generate BBCode release text for *that* Russian Steam forum
- Stores Steam credentials in the system keyring (GNOME Keyring / KWallet)
- First run prompts for Steam login; later runs can auto-login from remembered Steam session data
- Supports Steam Guard code entry

<p align="center">
  <img src="data/icons/hicolor/scalable/apps/org.gnusteampacker.GnuSteamPacker.svg" alt="GnuSteamPacker icon" width="128">
</p>


## Icon

The current app icon is a placeholder AI slop design - if you'd like to design a proper logo for GnuSteamPacker, contributions are very welcome! Open an issue or PR.

## Download

| Distro | Package |
|--------|---------|
| Fedora, RHEL, openSUSE | [.rpm](https://github.com/SavageCore/GnuSteamPacker/releases/latest) |
| Debian, Ubuntu, Mint | [.deb](https://github.com/SavageCore/GnuSteamPacker/releases/latest) |
| Any Linux (x86_64) | [.AppImage](https://github.com/SavageCore/GnuSteamPacker/releases/latest) |
| Flatpak | [Remote (auto-updates)](#flatpak) · [.flatpak bundle](https://github.com/SavageCore/GnuSteamPacker/releases/latest) |

## Flatpak

Install via the self-hosted remote for automatic updates:

```bash
# Add remote (once)
curl -sL https://SavageCore.github.io/GnuSteamPacker/gnusteampacker-flatpak.gpg \
  -o /tmp/gnusteampacker-flatpak.gpg
flatpak remote-add --user \
  --gpg-import=/tmp/gnusteampacker-flatpak.gpg \
  gnusteampacker https://SavageCore.github.io/GnuSteamPacker/

# Install
flatpak install gnusteampacker org.gnusteampacker.GnuSteamPacker

# Update (or use GNOME Software / Flatpost)
flatpak update org.gnusteampacker.GnuSteamPacker
```

Alternatively, install the bundle directly from [Releases](https://github.com/SavageCore/GnuSteamPacker/releases/latest) (no automatic updates):

```bash
flatpak install --user --bundle gnusteampacker.flatpak
```

## Requirements

- Python 3.11+
- GTK4 + libadwaita (`python3-gobject`, `libadwaita`)
- `7zip` / `7z`
- `uv` (for development)
- `gettext` (for compiling translations - provides `msgfmt`/`xgettext`/`msgmerge`)

On Fedora/Nobara:

```bash
sudo dnf install python3-gobject libadwaita 7zip gettext
```

On Arch/CachyOS:

```bash
sudo pacman -S python-gobject libadwaita p7zip uv gettext
```

On Debian/Ubuntu:

```bash
sudo apt install python3-gi gir1.2-adw-1 p7zip-full gettext
pip install uv  # uv is not in Debian repos
```

## Development

Set up the virtual environment:

```bash
make dev
```

Run the app:

```bash
make run
```

Watch for file changes and auto-restart on save:

```bash
make watch
```

Lint and format:

```bash
make lint
make format
```

Install pre-commit hooks (runs ruff automatically on each commit):

```bash
uv run pre-commit install
```

Compare generated output against SuperSteamPacker references:

```bash
python scripts/compare_outputs.py
```

## Headless CLI

For automating release runs, GnuSteamPacker has a headless `pack` subcommand that
downloads, cleans, and compresses a build for one or more platforms without opening
the GUI:

```bash
gnusteampacker pack 1902940 --platforms win64,lin64 --branch public
```

Store your Steam credentials once before running pack:

```bash
gnusteampacker pack login steam
```

If Steam Guard is required, you'll be prompted for the code interactively on the first download.

| Flag | Default | Description |
|------|---------|-------------|
| `-p`, `--platforms` | `win64,lin64` | Comma-separated platform keys: `win64`, `win32`, `lin64`, `lin32`, `macos` |
| `-b`, `--branch` | `public` | Steam branch to download |
| `-B`, `--branch-password` | _(none)_ | Password for a private branch |
| `-v`, `--version` | _(none)_ | Human version string for the forum reply, e.g. `1.3.5` (prompted if omitted) |
| `-u`, `--forum-post-url` | _(none)_ | URL of the release post; cached per-appid (prompted on first use after the first pack) |
| `-n`, `--no-open` | off | Don't auto-open the SteamDB patch notes page in your browser |
| `-U`, `--upload` | off | Upload the packaged files to multiup.io |
| `-a`, `--anonymous` | off | Upload anonymously, bypassing stored multiup.io credentials |

On success, `pack`:
1. Prints paths to the generated `.7z` archives, ready to upload to multiup.io (if `--upload` was omitted)
2. Prompts for the new version number (opens your browser to the SteamDB patch notes page so you can find it).
   On the first pack for a game, the forum post URL prompt is skipped since there's no existing post to reply to.
3. Merges the new per-platform BBCode blocks into the cached forum post for this game (stored in
   `~/.local/share/gnusteampacker/forum_posts/<appid>.txt`), shifting the previous release into
   a "Previous Versions" spoiler. Writes the result to `<game>.ForumPost.Build.<id>.txt` in the
   output directory and updates the cache for next time.
4. Prints a forum reply template e.g. `[url=...]Updated[/url] to [url=...]1.0.0[/url]`
   (skipped on first pack).

### Steam credentials

To store your Steam credentials for headless use:

```bash
gnusteampacker pack login steam
```

This prompts for your username and password and stores them in your system keyring (or a fallback
file at `~/.config/gnusteampacker/.{username,password}` if no keyring is available). Credentials
are used automatically on every subsequent `pack` run.

To clear stored credentials (e.g. to switch accounts or re-test):

```bash
secret-tool clear service gnusteampacker key username
secret-tool clear service gnusteampacker key password
```

### multiup.io credentials

To upload as a logged-in multiup.io user, save your credentials once:

```bash
gnusteampacker pack login multiup
```

This prompts for your username and password, verifies them against the multiup.io API,
and stores them in your system keyring (or a fallback file if no keyring is available).
Credentials are then used automatically whenever you run with `--upload`.

If no credentials are saved when you run `--upload`, you'll be prompted inline and given
the option to upload anonymously instead.

## Translations

GnuSteamPacker is translated via [Crowdin](https://crowdin.com/project/gnusteampacker). If you'd like to contribute a translation or improve an existing one, head to the project's Crowdin page - no Git knowledge required, just sign in and start translating.

Local development commands for working with translations directly:

```bash
make pot        # Regenerate po/gnusteampacker.pot from source strings
make update-po  # Merge the regenerated template into existing po/*.po files
make mo         # Compile po/*.po into gnusteampacker/locale/<lang>/LC_MESSAGES/*.mo
```

`make dev` and `make run` compile translations automatically. To run the app in a specific language:

```bash
LANGUAGE=ru make run
```

To add a new language, create `po/<lang>.po` (e.g. via `msginit --input=po/gnusteampacker.pot --locale=<lang> --output=po/<lang>.po`) and add `<lang>` to `po/LINGUAS`.

## Packaging

Build a Flatpak:

```bash
make flatpak
make flatpak-run
```

Build an RPM or DEB (requires `nfpm` and `envsubst` from `gettext`):

```bash
make rpm
make deb
```

Three packages are produced in `dist-packages/`:

| Package | Contents | Use when |
|---------|----------|----------|
| `gnusteampacker-full` | CLI + GUI | Local install (recommended) |
| `gnusteampacker` | CLI only | Repo-based install without GUI |
| `gnusteampacker-gui` | GTK4 GUI add-on | Repo-based install, depends on `gnusteampacker` |

## License

GPL-3.0-or-later
