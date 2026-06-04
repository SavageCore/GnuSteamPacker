# GnuSteamPacker

A Linux-native GUI for downloading, cleaning, and packaging Steam games for archival and sharing. Spiritual port of [SuperSteamPacker](https://github.com/Masquerade64/SuperSteamPacker) built with Python, GTK4, and libadwaita.

Features:
- Search Steam for games by name or AppID
- Download via SteamCMD (auto-installed on first run)
- Strip privacy-sensitive data from ACF/VDF files
- Compress to a single `.7z` archive
- Generate BBCode release text for *that* Russian Steam forum
- Stores Steam credentials in the system keyring (GNOME Keyring / KWallet)

## Download

| Distro | Package |
|--------|---------|
| Fedora, RHEL, openSUSE | [.rpm](https://github.com/SavageCore/GnuSteamPacker/releases/latest) |
| Debian, Ubuntu, Mint | [.deb](https://github.com/SavageCore/GnuSteamPacker/releases/latest) |
| Any Linux (x86_64) | [.AppImage](https://github.com/SavageCore/GnuSteamPacker/releases/latest) |
| Flatpak | [.flatpak](https://github.com/SavageCore/GnuSteamPacker/releases/latest) |

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
