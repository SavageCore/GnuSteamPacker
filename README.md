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

This requires Steam credentials to already be configured via the GUI's Preferences
(GnuSteamPacker stores them in your system keyring). If Steam Guard is required,
you'll be prompted for the code interactively.

| Flag | Default | Description |
|------|---------|-------------|
| `--platforms` | `win64,lin64` | Comma-separated platform keys: `win64`, `win32`, `lin64`, `lin32`, `macos` |
| `--branch` | `public` | Steam branch to download |
| `--branch-password` | _(none)_ | Password for a private branch |
| `--version` | _(none)_ | Human version string for the forum reply, e.g. `1.3.5` (prompted if omitted) |
| `--forum-post-url` | _(none)_ | URL of the release post; cached per-appid (prompted on first use for an appid) |
| `--no-open` | off | Don't auto-open the SteamDB patch notes page in your browser |
| `--upload` | _(none)_ | Should we upload to multiup.io? You can either upload annoymously or set credentials below
| `--multiup-user` | _(none)_ | Username at multiup.io (optional)
| `--multiup-pass` | _(none)_ | Password at multiup.io (optional)

On success, `pack`:
1. Prints paths to the generated `.7z` archives, ready to upload to multiup.io (if `--upload` was omitted)
2. Prompts for the forum post URL (cached per-appid for next time) and the new
   version number. It'll open your browser to the SteamDB patch notes page for the build so you can easily find it.
3. Prompts for the *current* release post content (paste it directly, finishing
   with Ctrl+D, or enter a path to a file containing it) - an example is at `examples/topic-bbcode.txt`
4. Moves those current release blocks into the "Previous Versions" spoiler,
   inserts the new BBCode for each platform at the top, and writes the result
   to `<game>.ForumPost.Build.<id>.txt` in the output directory, ready to paste
   back into the forum (after filling in the new multiup links if `--upload` was omitted)
5. Prints a forum reply template using the forum post URL and version e.g. (`[url=https://cs.rin.ru/forum/viewtopic.php?p=1234#p1234]Updated[/url] to [url=https://steamdb.info/patchnotes/xxxxxxxx/]1.0.0[/url]`)

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

Build an RPM or DEB (requires `nfpm`):

```bash
make rpm
make deb
```

## License

GPL-3.0-or-later
