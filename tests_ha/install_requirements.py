"""Install declared HA test integration requirements from its pinned distribution."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

root = Path(importlib.util.find_spec("homeassistant").submodule_search_locations[0])
seen, requirements = set(), set()


def collect(domain):
    if domain in seen:
        return
    seen.add(domain)
    manifest = json.loads((root / "components" / domain / "manifest.json").read_text())
    requirements.update(manifest.get("requirements", []))
    for dependency in manifest.get("dependencies", []):
        collect(dependency)


for domain in (
    "bluetooth",
    "lock",
    "sensor",
    "select",
    "switch",
    "button",
    "hassio",
    "backup",
    "http",
    "websocket_api",
):
    collect(domain)
if requirements:
    subprocess.run(
        [sys.executable, "-m", "pip", "install", *sorted(requirements)], check=True
    )
