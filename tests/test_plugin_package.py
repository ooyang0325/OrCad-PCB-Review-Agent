import json
from pathlib import Path
import tomllib
import unittest

from orcad_placement_agent import __version__


class PluginPackageTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1]

    def read(self, path):
        return json.loads((self.root / path).read_text(encoding="utf-8"))

    def test_portable_and_claude_manifests_have_one_identity(self):
        portable = self.read("plugin.json")
        claude = self.read(".claude-plugin/plugin.json")
        project = tomllib.loads((self.root / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(portable["$schema"], "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json")
        self.assertEqual(portable["name"], "orcad-placement")
        self.assertEqual(portable["name"], claude["name"])
        self.assertEqual({portable["version"], claude["version"], project["project"]["version"]}, {__version__})
        self.assertTrue(set(portable) <= {
            "$schema", "name", "version", "description", "author", "homepage",
            "repository", "license", "keywords", "extensions",
        })
        self.assertNotIn("extensions", portable)
        self.assertNotIn("hooks", claude)
        self.assertNotIn("license", portable)
        self.assertFalse((self.root / ".mcp.json").exists())

    def test_each_client_expands_only_its_documented_plugin_root(self):
        portable = self.read("mcp.json")
        self.assertEqual(portable["$schema"], "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json")
        for config, variable in [
            (portable, "${PLUGIN_ROOT}"),
            (self.read(".claude-plugin/plugin.json"), "${CLAUDE_PLUGIN_ROOT}"),
        ]:
            self.assertEqual(set(config["mcpServers"]), {"orcad-placement"})
            server = config["mcpServers"]["orcad-placement"]
            self.assertEqual(server["type"], "stdio")
            self.assertEqual(server["command"], "py")
            self.assertEqual(server["args"][:4], ["-3", "-I", "-X", "utf8"])
            self.assertNotIn("--allow-interactive-writes", server["args"])
            self.assertNotIn("-ExecutionPolicy", server["args"])
            resolved = Path(server["args"][-1].replace(variable, str(self.root))).resolve()
            self.assertTrue(resolved.is_relative_to(self.root))
            self.assertTrue(resolved.is_file())
            self.assertNotIn("url", server)

    def test_marketplaces_point_to_the_same_self_contained_root(self):
        claude = self.read(".claude-plugin/marketplace.json")
        codex = self.read(".agents/plugins/marketplace.json")
        self.assertEqual(claude["name"], codex["name"])
        self.assertEqual(claude["plugins"][0]["source"], "./")
        entry = codex["plugins"][0]
        self.assertEqual(entry["name"], "orcad-placement")
        self.assertEqual(entry["source"], {"source": "local", "path": "./"})
        self.assertEqual(entry["policy"]["installation"], "AVAILABLE")
        self.assertEqual(entry["policy"]["authentication"], "ON_INSTALL")
        self.assertEqual(entry["category"], "Productivity")
        self.assertEqual(claude["plugins"][0]["version"], __version__)

    def test_portable_skills_are_self_contained_and_visual(self):
        skills = list((self.root / "skills").glob("*/SKILL.md"))
        self.assertEqual(len(skills), 4)
        for path in skills:
            text = path.read_text(encoding="utf-8")
            frontmatter, body = text.split("---", 2)[1:]
            fields = dict(line.split(":", 1) for line in frontmatter.splitlines() if line.strip())
            self.assertEqual(fields["name"].strip(), path.parent.name)
            self.assertRegex(fields["name"].strip(), r"^[a-z0-9-]+$")
            self.assertTrue(fields["description"].strip())
            self.assertIn("pcb_inspect", body)
            self.assertIn("PNG", body)
            self.assertIn("untrusted", body)
            self.assertIn("pcb_reference_rule", body)
            self.assertIn("textbooks", body)
            self.assertNotIn("${", body)
            self.assertNotIn("powershell", body.lower())
        execution = (self.root / "skills" / "pcb-placement-execute" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("disable-model-invocation: true", execution)
        self.assertIn("read-only by default", execution)
        self.assertIn("allow_implicit_invocation: false",
                      (self.root / "skills" / "pcb-placement-execute" / "agents" / "openai.yaml").read_text())
        coordinator = self.root / "skills" / "pcb-placement-orchestrate"
        self.assertIn("disable-model-invocation: true", (coordinator / "SKILL.md").read_text())
        self.assertIn("allow_implicit_invocation: false",
                      (coordinator / "agents" / "openai.yaml").read_text())

    def test_bootstraps_do_not_bypass_policies_or_modify_client_settings(self):
        install = (self.root / "scripts" / "install.py").read_text(encoding="utf-8")
        startup = (self.root / "scripts" / "start_mcp.py").read_text(encoding="utf-8")
        for script in (install, startup):
            self.assertNotIn("ExecutionPolicy", script)
            self.assertNotIn("shell=True", script)
            self.assertNotIn("Set-ExecutionPolicy", script)
        self.assertIn(".orcad-placement-environment.json", install)
        self.assertIn(".orcad-placement-environment.json", startup)
        self.assertIn("integration-config", install)
        self.assertNotIn('"pip"', startup)
        self.assertNotIn("pip install", startup)
        self.assertNotIn('environment_values["OPA_KNOWLEDGE_DB"] =', startup)
        self.assertIn('str(root) + "[integrations]"', install)


if __name__ == "__main__":
    unittest.main()
