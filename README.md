# GnuSteamPacker

A Linux-native GUI for downloading, cleaning, and packaging Steam games for archival and sharing. Spiritual port of [SuperSteamPacker](https://github.com/Masquerade64/SuperSteamPacker) built with Python, GTK4, and libadwaita.

Features:
- Search Steam for games by name or AppID
- Download via DepotDownloader (auto-installed on first run)
- Generate clean ACF manifest files
- Compress to a single `.7z` archive
- Generate BBCode release text for *that* Russian Steam forum
- Stores Steam credentials in the system keyring (GNOME Keyring / KWallet)
- First run prompts for Steam login; later runs can auto-login from remembered Steam session data
- Supports Steam Guard code entry and optional `qr` login flow via Steam mobile app

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
- `entr` (for `make watch`)

On Fedora/Nobara:

```bash
sudo dnf install python3-gobject libadwaita 7zip entr
```

On Arch/CachyOS:

```bash
sudo pacman -S python-gobject libadwaita p7zip entr uv
```

On Debian/Ubuntu:

```bash
sudo apt install python3-gi gir1.2-adw-1 p7zip-full entr
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
