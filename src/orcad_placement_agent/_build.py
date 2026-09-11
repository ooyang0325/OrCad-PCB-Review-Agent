"""Include original runtime assets without maintaining duplicate source copies."""

from pathlib import Path
import shutil

from setuptools.command.build_py import build_py


ASSETS = {
    "skill": ("probe.il", "protocol.il", "placement.il", "managed_board.il", "adapter.il"),
    "fixtures/access-proof": ("create.il", "opa_fixture_device.txt", "README.md"),
}


class BuildWithRuntimeAssets(build_py):
    def run(self):
        super().run()
        root = Path(__file__).resolve().parents[2]
        destination = Path(self.build_lib) / "orcad_placement_agent" / "_assets"
        for directory, names in ASSETS.items():
            for name in names:
                source = root / directory / name
                target = destination / directory / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
