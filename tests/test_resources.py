import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from orcad_placement_agent.cli import main
from orcad_placement_agent.diagnostics import ConfigurationError
from orcad_placement_agent.resources import asset_directory


class ResourceTests(unittest.TestCase):
    def test_original_runtime_asset_groups_are_available(self):
        skill = asset_directory("skill")
        self.assertTrue((skill / "adapter.il").is_file())
        self.assertTrue((skill / "probe.il").is_file())
        fixture = asset_directory("fixtures/access-proof")
        self.assertTrue((fixture / "opa_fixture_device.txt").is_file())
        with self.assertRaises(ConfigurationError):
            asset_directory("../doc")

    def test_default_assets_do_not_depend_on_the_callers_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            hostile = root / "skill"
            hostile.mkdir()
            (hostile / "probe.il").write_text("untrusted caller file", encoding="ascii")
            output = io.StringIO()
            with contextlib.chdir(root), contextlib.redirect_stdout(output):
                code = main(["stage-probe", "--runtime-dir", str(root / "sessions"), "--json"])
            self.assertEqual(code, 0)
            staged = json.loads(output.getvalue())
            self.assertNotIn(
                "untrusted caller file",
                (Path(staged["session_directory"]) / "probe.il").read_text(encoding="ascii"),
            )


if __name__ == "__main__":
    unittest.main()
