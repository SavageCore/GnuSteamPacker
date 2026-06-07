"""GNOME Secret Service credential storage with plaintext fallback."""

from pathlib import Path

from gnusteampacker.config import CONFIG_DIR

_COLLECTION = "gnusteampacker"
_USER_ATTR = {"service": _COLLECTION, "key": "username"}
_PASS_ATTR = {"service": _COLLECTION, "key": "password"}

_FALLBACK_FILE = CONFIG_DIR / ".credentials"


def _keyring():
    try:
        import secretstorage

        bus = secretstorage.dbus_init()
        col = secretstorage.get_default_collection(bus)
        if col.is_locked():
            col.unlock()
        return col
    except Exception:
        return None


def get_username() -> str:
    col = _keyring()
    if col:
        try:
            items = list(col.search_items(_USER_ATTR))
            if items:
                return items[0].get_secret().decode()
        except Exception:
            pass
    return _fallback_read("username")


def get_password() -> str:
    col = _keyring()
    if col:
        try:
            items = list(col.search_items(_PASS_ATTR))
            if items:
                return items[0].get_secret().decode()
        except Exception:
            pass
    return _fallback_read("password")


def set_username(value: str) -> None:
    col = _keyring()
    if col:
        try:
            for item in col.search_items(_USER_ATTR):
                item.delete()
            col.create_item("GnuSteamPacker username", _USER_ATTR, value.encode())
            return
        except Exception:
            pass
    _fallback_write("username", value)


def set_password(value: str) -> None:
    col = _keyring()
    if col:
        try:
            for item in col.search_items(_PASS_ATTR):
                item.delete()
            col.create_item("GnuSteamPacker password", _PASS_ATTR, value.encode())
            return
        except Exception:
            pass
    _fallback_write("password", value)


def clear_password() -> None:
    set_password("")


def clear_username() -> None:
    set_username("")


def _fallback_path(key: str) -> Path:
    return CONFIG_DIR / f".{key}"


def _fallback_read(key: str) -> str:
    p = _fallback_path(key)
    if p.exists():
        return p.read_text().strip()
    return ""


def _fallback_write(key: str, value: str) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    p = _fallback_path(key)
    p.write_text(value)
    p.chmod(0o600)
