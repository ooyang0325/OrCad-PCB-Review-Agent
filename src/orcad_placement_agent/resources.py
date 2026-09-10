"""Locate trusted runtime assets independently of a client's working directory."""

from pathlib import Path
import tomllib

from .diagnostics import ConfigurationError


def asset_directory(name: str) -> Path:
    if name not in {"skill", "fixtures/access-proof"}:
        raise ConfigurationError("Unknown runtime asset group.")
    package = Path(__file__).resolve().parent
    bundled = package / "_assets" / name
    if bundled.is_dir():
        return bundled
    checkout = package.parents[1]
    manifest = checkout / "pyproject.toml"
    if manifest.is_file():
        with manifest.open("rb") as source:
            metadata = tomllib.load(source)
        if metadata.get("project", {}).get("name") == "orcad-placement-agent":
            development = checkout / name
            if development.is_dir():
                return development
    raise ConfigurationError(
        f"Trusted {name} assets are unavailable. Reinstall from the complete repository or wheel."
    )
