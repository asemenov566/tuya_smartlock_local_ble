"""Build an install-only ZIP from an explicit, reviewable file allowlist."""

import hashlib
import json
import re
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = Path("custom_components/tuya_smartlock_local_ble")
# New runtime files require an explicit packaging review. Never glob credentials.
FILES = """
LICENSE
__init__.py
application/__init__.py
application/lock_actions.py
application/lock_commands.py
application/lock_status.py
application/session_policy.py
brand/icon.png
button.py
config_flow.py
connections.py
const.py
devices.py
domain/__init__.py
domain/command_context.py
domain/contracts.py
domain/credentials.py
domain/datapoints.py
keepalive.py
keyman.py
lock.py
manifest.json
models/__init__.py
models/a1_ultra.py
protocols/__init__.py
protocols/tuya_ble/__init__.py
protocols/tuya_ble/codec.py
protocols/tuya_ble/commands/__init__.py
protocols/tuya_ble/commands/unlock_check.py
protocols/tuya_ble/commands/write.py
protocols/tuya_ble/const.py
protocols/tuya_ble/dialects/__init__.py
protocols/tuya_ble/dialects/fd50.py
protocols/tuya_ble/exceptions.py
protocols/tuya_ble/reports.py
protocols/tuya_ble/session.py
registry.py
select.py
sensor.py
strings.json
switch.py
translations/en.json
translations/ru.json
transports/__init__.py
transports/ble.py
""".split()


def package_files(root):
    """Read only declared regular files; reject links or a missing deliverable."""
    root = Path(root).resolve()
    result = {}
    for name in FILES:
        relative = COMPONENT / name
        path = root / relative
        for part in (path, *path.parents):
            if part == root:
                break
            if part.is_symlink() or getattr(part, "is_junction", lambda: False)():
                raise ValueError(f"Packaging links is forbidden: {relative}")
        if not path.resolve().is_relative_to(root) or not path.is_file():
            raise ValueError(f"Missing or unsafe package file: {relative}")
        result[relative.as_posix()] = path.read_bytes()
    return result


def build_archive(root, output):
    files = package_files(root)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, "x", compression=ZIP_DEFLATED) as archive:
        for name, content in sorted(files.items()):
            info = ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, content)
    with ZipFile(output) as archive:
        if set(archive.namelist()) != set(files) or any(
            archive.read(name) != content for name, content in files.items()
        ):
            raise RuntimeError("Built archive does not match the declared source files")
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(output.suffix + ".sha256").write_text(
        f"{digest}  {output.name}\n", encoding="ascii"
    )
    return output


if __name__ == "__main__":
    version = json.loads((ROOT / COMPONENT / "manifest.json").read_text())["version"]
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:[a-zA-Z0-9.-]+)?", version):
        raise SystemExit("Invalid package version")
    result = build_archive(ROOT, ROOT / "dist" / f"tuya_smartlock_local_ble-{version}.zip")
    print(f"Verified {len(FILES)} runtime files in dist/{result.name}")
