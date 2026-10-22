"""Build a reviewable shadow deployment ZIP without touching the running installation."""

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from . import __version__
from .config import Config
from .validation import mapping


def build(root: Path, destination: Path) -> Path:
    import yaml

    root = root.resolve()
    args = mapping(yaml.safe_load((root / "cfg/app_cfg.yaml").read_text(encoding="utf-8")))
    name = next(iter(args))
    app = mapping(args[name])
    settings = mapping(app["v2"])
    if (
        settings.get("shadow") is not True
        or app.get("module") != "SmartHeating2.smartheating.appdaemon_app"
    ):
        raise ValueError("This packager only builds the isolated observation deployment")
    commit = subprocess.check_output(
        ["git", "rev-parse", "--short", "HEAD"], cwd=root, text=True
    ).strip()
    dirty = subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True).strip()
    settings["commit"] = commit + ("+dirty" if dirty else "")
    config = Config.parse(app)
    payloads: dict[str, bytes] = {
        "__init__.py": b'"""AppDaemon deployment package for SmartHeating observation."""\n'
    }
    for path in sorted((root / "src/smartheating").glob("*.py")):
        payloads[f"smartheating/{path.name}"] = path.read_bytes()
    payloads["apps.yaml"] = yaml.safe_dump(args, sort_keys=False, allow_unicode=True).encode(
        "utf-8"
    )
    manifest = {
        "version": __version__,
        "commit": settings["commit"],
        "config_id": config.config_id,
        "mode": "shadow",
        "physical_writes": False,
        "files": {key: hashlib.sha256(value).hexdigest() for key, value in payloads.items()},
    }
    payloads["manifest.json"] = json.dumps(manifest, indent=2).encode("utf-8")
    destination.mkdir(parents=True, exist_ok=True)
    output = destination / f"smartheating-{__version__}-shadow.zip"
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for filename, content in payloads.items():
            archive.writestr(filename, content)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, default=Path("dist"))
    args = parser.parse_args()
    print(build(Path(args.root), Path(args.output)))


if __name__ == "__main__":
    main()
