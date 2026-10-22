import hashlib
import importlib
import json
import sys
import types
from pathlib import Path
from zipfile import ZipFile

import yaml

from smartheating.bundle import build


def test_bundle_imports_by_the_configured_appdaemon_package(tmp_path, monkeypatch):
    artifact = build(Path.cwd(), tmp_path)
    apps = tmp_path / "apps"
    destination = apps / "SmartHeating2"
    with ZipFile(artifact) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert all(
            hashlib.sha256(archive.read(k)).hexdigest() == v for k, v in manifest["files"].items()
        )
        assert "SmartHeating.py" not in archive.namelist()
        assert not any(k.startswith("legacy/") for k in archive.namelist())
        archive.extractall(destination)
    module = types.ModuleType("appdaemon_common")
    module.HealthAppBase = type("HealthAppBase", (), {})
    module.init_step = lambda *args, **kwargs: lambda method: method
    monkeypatch.setitem(sys.modules, "appdaemon_common", module)
    monkeypatch.syspath_prepend(str(apps))
    raw = next(
        iter(yaml.safe_load((destination / "apps.yaml").read_text(encoding="utf-8")).values())
    )
    try:
        deployed = importlib.import_module(raw["module"])
        assert deployed.SmartHeating.__module__ == raw["module"]
        assert raw["v2"]["shadow"]
        assert not raw["v2"]["active_authorized"]
    finally:
        for key in list(sys.modules):
            if key == "SmartHeating2" or key.startswith("SmartHeating2."):
                del sys.modules[key]
