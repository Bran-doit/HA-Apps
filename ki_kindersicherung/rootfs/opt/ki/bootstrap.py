"""Prepare the private AppDaemon runtime and seed persistent app data."""
import os
from pathlib import Path
from shutil import copyfile

import yaml

source = Path("/opt/ki/source/appdaemon")
runtime = Path("/run/ki")
data = Path("/data/ki_kindersicherung/config.yaml")
if not data.exists():
    copyfile(source / "config.example.yaml", data)

app = (source / "app.py").read_text(encoding="utf-8")
# Views live one level below the Ingress root. Relative URLs retain its prefix.
app = app.replace("__APPDAEMON_URL__/app/", "../app/")
app = app.replace("'/app/ki_kindersicherung_", "'../app/ki_kindersicherung_")
app = app.replace("/api/appdaemon/", "../api/appdaemon/")
(runtime / "apps/ki_kindersicherung/app.py").write_text(app, encoding="utf-8")
(runtime / "apps/ki_kindersicherung/__init__.py").touch()
(runtime / "apps/apps.yaml").write_text(yaml.safe_dump({
    "ki_kindersicherung": {
        "module": "ki_kindersicherung.app",
        "class": "KiKindersicherung",
        "config_file": str(data),
        "tv_display_supported": False,
    },
}), encoding="utf-8")
configuration = {
    "appdaemon": {
        "time_zone": os.environ.get("TZ", "UTC"),
        "latitude": 0,
        "longitude": 0,
        "elevation": 0,
        "plugins": {
            "HASS": {
                "type": "hass",
                "ha_url": "http://supervisor/core",
                "token": os.environ["SUPERVISOR_TOKEN"],
            },
        },
    },
    "http": {"url": "http://127.0.0.1:5050"},
    "api": {},
}
config_path = runtime / "appdaemon.yaml"
config_path.touch(mode=0o600)
config_path.write_text(yaml.safe_dump(configuration), encoding="utf-8")
