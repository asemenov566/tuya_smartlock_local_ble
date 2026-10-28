"""Run synthetic tests in a temporary profile, without real BLE/network/database I/O."""

import argparse
import os
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SUITES = {"protocol": "tests", "ha": "tests_ha", "packaging": "tests_packaging"}


def guard_io(profile):
    """Process-local guard; importing this module alone does not install it."""
    def audit(event, args):
        if event == "socket.connect":
            # Windows implements asyncio's local socketpair using loopback TCP.
            frame = sys._getframe(1)
            if (frame.f_globals.get("__name__") == "socket"
                    and frame.f_code.co_name in ("socketpair", "_fallback_socketpair")
                    and args[0].family in (socket.AF_INET, socket.AF_INET6)
                    and args[1][0] in ("127.0.0.1", "::1")):
                return
            raise RuntimeError("Tests must not connect to real services")
        if event == "socket.sendto":
            raise RuntimeError("Tests must not send network datagrams")
        if event == "sqlite3.connect" and args[0] != ":memory:":
            raise RuntimeError("Tests may only use an in-memory SQLite database")
        if event == "open" and isinstance(args[0], (str, bytes, os.PathLike)):
            path = Path(os.fsdecode(args[0])).resolve()
            if ".storage" in path.parts and not path.is_relative_to(profile):
                raise RuntimeError("Tests must not read a real HA profile")
            flags = args[2] if len(args) > 2 else 0
            if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC):
                if path != Path(os.devnull).resolve() and not path.is_relative_to(profile):
                    raise RuntimeError("Tests may only write inside the temporary profile")
    sys.addaudithook(audit)


async def no_radio(*args, **kwargs):
    raise RuntimeError("Tests must mock Bluetooth access")


def expand_test_home(path, profile):
    """Resolve the current user's home only to the disposable test profile."""
    path = os.fsdecode(path)
    if path == "~":
        return str(profile)
    if path.startswith(("~/", "~\\")):
        return str(profile / path[2:])
    if path.startswith("~"):
        raise RuntimeError("Tests must not resolve another user's home")
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("suite", choices=SUITES)
    args = parser.parse_args()
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(ROOT))
    with tempfile.TemporaryDirectory(prefix="smartlock-tests-") as temporary:
        profile = Path(temporary).resolve()
        os.chdir(profile)
        for key in ("HASS_CONFIG", "HA_CONFIG", "XDG_CONFIG_HOME", "XDG_CACHE_HOME",
                    "USERPROFILE", "APPDATA", "LOCALAPPDATA", "TMP", "TEMP", "TMPDIR"):
            os.environ[key] = str(profile)
        # tempfile caches its directory before the environment is changed.
        tempfile.tempdir = str(profile)
        guard_io(profile)
        try:
            if args.suite != "packaging":
                import bleak
                import bleak_retry_connector

                bleak.BleakClient.connect = no_radio
                bleak.BleakScanner.start = no_radio
                bleak_retry_connector.establish_connection = no_radio
            with (patch.object(Path, "home", return_value=profile),
                  patch("os.path.expanduser", side_effect=lambda value: expand_test_home(value, profile))):
                suite = unittest.TestLoader().discover(str(ROOT / SUITES[args.suite]))
                result = unittest.TextTestRunner(verbosity=2).run(suite)
        finally:
            os.chdir(ROOT)
    return not result.wasSuccessful()


if __name__ == "__main__":
    raise SystemExit(main())
