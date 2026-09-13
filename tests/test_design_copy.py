import contextlib
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from orcad_placement_agent import design_copy
from orcad_placement_agent.cli import main
from orcad_placement_agent.resources import asset_directory
from orcad_placement_agent.session import Session, SessionError, file_digest, stage_session


class DesignCopyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self.board = self.project / "howto.brd"
        self.board.write_bytes(b"original synthetic board bytes")
        self.runtime = self.root / "sessions"
        self.skill = asset_directory("skill")

    def add(self, name, content=b"original synthetic project data"):
        path = self.project / design_copy.relative_path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def stage(self, **options):
        return stage_session(self.board, self.runtime, self.skill, model="managed-board-v1", **options)

    def test_unverified_3d_requires_explicit_session_bound_staging_policy(self):
        strict = Session(self.stage())
        self.assertFalse(strict.allow_unverified_3d)
        selected = Session(self.stage(allow_unverified_3d=True))
        self.assertTrue(selected.allow_unverified_3d)
        self.assertEqual(selected._read_json("session.json")["schema_version"], 4)
        bootstrap = (selected.root / "bootstrap.il").read_text()
        self.assertIn(f'opaUnverified3DNonce = "{selected.nonce}"', bootstrap)
        self.assertEqual(selected.working.read_bytes(), self.board.read_bytes())
        with self.assertRaises(SessionError):
            self.stage(allow_unverified_3d=True, board_only=True)
        with self.assertRaises(SessionError):
            stage_session(self.board, self.runtime, self.skill, allow_unverified_3d=True)

    def test_default_copies_complete_tree_and_keeps_controller_files_separate(self):
        for name in ("parts\\cap.psm", "parts\\cap.pad", "parts\\ab00.fsm", "parts\\cap.dra",
                     "pstchip.dat", "pstxprt.dat", "assembly.step", "readme.txt", ".hidden-data",
                     "session.json", "bootstrap.il", "adapter.il", "allegro.ilinit", "env", "custom.scr"):
            self.add(name)
        (self.project / "empty").mkdir()
        before = {str(path.relative_to(self.project)): path.read_bytes()
                  for path in self.project.rglob("*") if path.is_file()}
        root = self.stage()
        session = Session(root)
        self.assertEqual(session.model, "managed-board-v1")
        self.assertEqual(session.working.read_bytes(), self.board.read_bytes())
        for relative, content in before.items():
            self.assertEqual((root / "design-data" / relative).read_bytes(), content)
            self.assertEqual((root / "design-data" / relative).stat().st_mtime_ns,
                             (self.project / relative).stat().st_mtime_ns)
        self.assertTrue((root / "design-data" / "empty").is_dir())
        self.assertEqual((root / "adapter.il").read_bytes(), (self.skill / "adapter.il").read_bytes())
        self.assertNotEqual((root / "session.json").read_bytes(), (self.project / "session.json").read_bytes())
        self.assertNotIn("design-data", (root / "bootstrap.il").read_text())
        self.assertFalse((root / "allegro.ilinit").exists())
        self.assertFalse((root / "env").exists())
        self.assertEqual(before, {str(path.relative_to(self.project)): path.read_bytes()
                                  for path in self.project.rglob("*") if path.is_file()})
        summary = session.design_summary()
        self.assertEqual(summary["file_count"], len(before))
        self.assertEqual(summary["library_files"], {"packages": 1, "padstacks": 1, "flash_or_shape_symbols": 1})
        self.assertEqual(summary["library_directories"]["psmpath"], [str(root / "design-data" / "parts")])
        self.assertIn("No libraries or scripts were loaded", summary["notice"])
        for entry in session.design_copy["files"]:
            path = root / "design-data" / design_copy.relative_path(entry["path"])
            self.assertEqual(file_digest(path), entry["sha256"])

    def test_explicit_design_root_includes_sibling_libraries(self):
        board_folder = self.project / "allegro"
        board_folder.mkdir()
        self.board.rename(board_folder / "howto.brd")
        self.board = board_folder / "howto.brd"
        self.add("libraries\\cap.psm")
        default = self.stage()
        self.assertFalse((default / "design-data" / "libraries").exists())
        expanded = self.stage(design_root=self.project)
        self.assertTrue((expanded / "design-data" / "libraries" / "cap.psm").is_file())
        self.assertTrue((expanded / "design-data" / "allegro" / "howto.brd").is_file())
        self.assertEqual(Session(expanded).design_copy["board_relative"], r"allegro\howto.brd")

    def test_locks_journals_backups_git_and_runtime_are_excluded_and_reported(self):
        excluded = ("howto.brd.lck", "allegro.jrl", "allegro.jrl,1", "tool.log",
                    "tool.log,2", "auto_backup.brd,1", "draft.tmp", "draft.bak", ".git",
                    ".venv\\Scripts\\python.exe", ".runtime\\knowledge.sqlite3",
                    "node_modules\\dependency.js", "__pycache__\\cached.pyc")
        for name in excluded:
            self.add(name)
        self.runtime = self.project / "staging-output"
        root = self.stage()
        copied = root / "design-data"
        self.assertFalse((copied / "staging-output").exists())
        for name in excluded:
            self.assertFalse((copied / design_copy.relative_path(name)).exists(), name)
        skipped = {entry["path"]: entry["reason"] for entry in Session(root).design_copy["skipped"]}
        self.assertIn("howto.brd.lck", skipped)
        self.assertIn(".git", skipped)
        self.assertIn(".venv", skipped)
        self.assertIn("staging-output", skipped)
        # Re-staging the source does not copy the previously created sessions.
        again = self.stage()
        self.assertEqual(Session(again).design_summary()["file_count"], 1)

    def test_board_only_preserves_old_session_schemas(self):
        self.add("cap.psm")
        root = self.stage(board_only=True)
        self.assertEqual(json.loads((root / "session.json").read_text())["schema_version"], 2)
        self.assertIsNone(Session(root).design_summary())
        self.assertFalse((root / "design-data").exists())
        fixture = stage_session(self.board, self.runtime, self.skill, board_only=True)
        self.assertEqual(json.loads((fixture / "session.json").read_text())["schema_version"], 1)
        self.assertEqual(Session(fixture).model, "fixture")
        with self.assertRaises(SessionError):
            self.stage(board_only=True, design_root=self.project)

    def test_new_nested_runtime_ancestors_do_not_enter_the_source_snapshot(self):
        self.runtime = self.project / "new-output" / "nested" / "sessions"
        root = self.stage()
        self.assertFalse((root / "design-data" / "new-output").exists())
        self.assertEqual(Session(root).design_summary()["file_count"], 1)

    def test_duplicate_library_names_remain_distinct_and_raise_a_warning(self):
        self.add("one\\cap.psm", b"first library")
        self.add("two\\cap.psm", b"second library")
        root = self.stage()
        summary = Session(root).design_summary()
        self.assertEqual((root / "design-data" / "one" / "cap.psm").read_bytes(), b"first library")
        self.assertEqual((root / "design-data" / "two" / "cap.psm").read_bytes(), b"second library")
        self.assertEqual(summary["library_name_conflicts"]["cap.psm"], [r"one\cap.psm", r"two\cap.psm"])
        self.assertTrue(summary["warnings"])

    def test_unicode_source_and_supporting_names_are_preserved_not_renamed(self):
        self.add("libraries\\\u96fb\u8def\\cap.psm")
        root = self.stage()
        self.assertTrue(str(root).isascii())
        self.assertTrue((root / "design-data" / "libraries" / "\u96fb\u8def" / "cap.psm").is_file())
        self.assertTrue(Session(root).design_summary()["warnings"])

    def test_invalid_roots_and_resource_limits_fail_before_session_creation(self):
        with self.assertRaises(SessionError):
            self.stage(design_root=self.root / "not-a-project")
        unrelated = self.root / "unrelated"
        unrelated.mkdir()
        with self.assertRaises(SessionError):
            self.stage(design_root=unrelated)
        with self.assertRaises(SessionError):
            stage_session(self.board, self.project, self.skill)
        self.add("cap.psm")
        for setting, maximum in (("MAX_FILES", 1), ("MAX_ENTRIES", 1),
                                 ("MAX_FILE_BYTES", 1), ("MAX_TOTAL_BYTES", 1)):
            with self.subTest(setting=setting), patch.object(design_copy, setting, maximum):
                with self.assertRaises(SessionError):
                    self.stage()
        self.assertFalse(self.runtime.exists())

    def test_deep_directories_and_read_errors_do_not_publish_a_session(self):
        (self.project / "one" / "two").mkdir(parents=True)
        with patch.object(design_copy, "MAX_DEPTH", 1):
            with self.assertRaises(SessionError):
                self.stage()
        self.assertFalse(self.runtime.exists())
        with patch.object(design_copy, "_copy_file", side_effect=PermissionError("Denied test input")):
            with self.assertRaisesRegex(SessionError, "no session was published"):
                self.stage()
        self.assertTrue(self.runtime.exists())
        self.assertFalse(list(self.runtime.glob(r"board-*\session.json")))

    def test_source_change_during_copy_is_explicit_and_no_session_is_published(self):
        self.add("cap.psm", b"before")
        original = design_copy._copy_file

        def change(source, destination, expected, root):
            if source.name == "cap.psm":
                source.write_bytes(b"changed during copy")
            return original(source, destination, expected, root)

        with patch.object(design_copy, "_copy_file", side_effect=change):
            with self.assertRaisesRegex(SessionError, "changed before copying"):
                self.stage()
        self.assertFalse(list(self.runtime.glob(r"board-*\session.json")))

    def test_added_or_removed_support_files_during_copy_are_detected(self):
        self.add("cap.psm")
        original = design_copy._copy_file

        def change(source, destination, expected, root):
            result = original(source, destination, expected, root)
            if source.name == "howto.brd":
                (self.project / "added.psm").write_bytes(b"new library")
            return result

        with patch.object(design_copy, "_copy_file", side_effect=change):
            with self.assertRaisesRegex(SessionError, "changed during staging"):
                self.stage()
        self.assertFalse(list(self.runtime.glob(r"board-*\session.json")))

    def test_removed_included_file_is_not_an_accepted_snapshot(self):
        library = self.add("cap.psm")
        original = design_copy._copy_file

        def change(source, destination, expected, root):
            result = original(source, destination, expected, root)
            if source.name == "howto.brd":
                library.unlink()
            return result

        with patch.object(design_copy, "_copy_file", side_effect=change):
            with self.assertRaisesRegex(SessionError, "changed during staging"):
                self.stage()
        self.assertFalse(list(self.runtime.glob(r"board-*\session.json")))

    def test_windows_case_alias_for_source_does_not_lose_the_selected_board(self):
        if os.name != "nt":
            self.skipTest("Windows case-insensitive input path behavior.")
        root = stage_session(Path(str(self.board).upper()), self.runtime, self.skill)
        self.assertEqual(Session(root).design_copy["board_relative"], "howto.brd")

    def test_resolution_never_adopts_a_redirected_external_root(self):
        outside = self.root / "outside-resolution"
        outside.mkdir()
        outside_board = outside / "howto.brd"
        outside_board.write_bytes(b"outside the selected folder")
        original = Path.resolve

        def redirect(path, *args, **kwargs):
            if path == self.board:
                return outside_board
            return original(path, *args, **kwargs)

        with patch.object(Path, "resolve", redirect):
            with self.assertRaisesRegex(SessionError, "different location"):
                self.stage()
        self.assertFalse(self.runtime.exists())

    def test_parent_directory_arguments_are_normalized_without_following_links(self):
        nested = self.project / "operator"
        nested.mkdir()
        with contextlib.chdir(nested):
            root = stage_session(Path("..") / "howto.brd", self.runtime, self.skill,
                                 model="managed-board-v1", design_root=Path(".."))
        self.assertEqual(Session(root).source, self.board)
        self.assertEqual(Session(root).design_summary()["file_count"], 1)

    @unittest.skipUnless(os.name == "nt", "Windows handle pinning test")
    def test_windows_resolution_keeps_ancestors_pinned_against_replacement(self):
        original = Path.resolve
        attempts = []

        def replace_ancestor(path, *args, **kwargs):
            if path == self.board and not attempts:
                attempts.append(True)
                with self.assertRaises(PermissionError):
                    self.project.rename(self.root / "moved-project")
            return original(path, *args, **kwargs)

        with patch.object(Path, "resolve", replace_ancestor):
            resolved = design_copy.resolve_input(self.board)
        self.assertEqual(resolved, self.board)
        self.assertEqual(attempts, [True])
        self.assertTrue(self.board.is_file())

    def test_verification_reads_only_the_expected_bytes_and_one_growth_probe(self):
        class EndlessGrowth:
            count = 0

            def read(self, size):
                self.count += size
                return b"x" * size

        reader = EndlessGrowth()
        with self.assertRaisesRegex(design_copy.DesignCopyError, "grew"):
            design_copy._bounded_hash(reader, 1)
        self.assertEqual(reader.count, 2)
        with self.assertRaisesRegex(design_copy.DesignCopyError, "shorter"):
            design_copy._bounded_hash(io.BytesIO(b"x"), 2)

    def test_copy_verification_never_uses_unbounded_file_digest(self):
        destination = self.root / "verified-copy.brd"
        expected = design_copy._signature(self.board.lstat())
        with patch.object(design_copy.hashlib, "file_digest", side_effect=AssertionError("Unbounded verification")):
            copied = design_copy._copy_file(self.board, destination, expected, self.project)
        self.assertEqual(copied["size"], self.board.stat().st_size)
        self.assertEqual(destination.read_bytes(), self.board.read_bytes())

    def test_changed_manifest_is_not_trusted_by_a_session(self):
        root = self.stage()
        path = root / "design-copy.json"
        manifest = json.loads(path.read_text())
        manifest["files"][0]["path"] = r"..\outside.psm"
        path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(SessionError, "manifest changed"):
            Session(root)

    def test_new_metadata_rejects_nonstring_model_and_boolean_version(self):
        for key, value in (("model", {}), ("schema_version", True)):
            with self.subTest(key=key):
                root = self.stage()
                path = root / "session.json"
                metadata = json.loads(path.read_text())
                metadata[key] = value
                path.write_text(json.dumps(metadata))
                with self.assertRaises(SessionError):
                    Session(root)

    def test_path_validation_rejects_escapes_reserved_names_and_aliases(self):
        for value in (".", "..", r"..\file", r"C:\outside", r"\outside", r"a\..\b",
                      r"a\.\b", "a/b", "NUL.psm", "file:stream", "ending.", "ending "):
            with self.subTest(value=value), self.assertRaises(design_copy.DesignCopyError):
                design_copy.relative_path(value)

    def test_cloud_files_are_not_treated_as_directory_redirections(self):
        def entry(tag):
            return SimpleNamespace(st_mode=stat.S_IFREG, st_reparse_tag=tag, st_file_attributes=0x400)
        self.assertFalse(design_copy._linked(entry(0x9000001A)))
        self.assertFalse(design_copy._linked(entry(0x9000601A)))
        self.assertTrue(design_copy._linked(entry(0xA000000C)))
        self.assertTrue(design_copy._linked(entry(0xA0000003)))
        self.assertTrue(design_copy._linked(entry(0x80000001)))

    def test_symlinks_are_rejected_without_copying_outside_content(self):
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "secret.psm").write_bytes(b"not in this design")
        try:
            (self.project / "link").symlink_to(outside, target_is_directory=True)
        except OSError as error:
            if getattr(error, "winerror", None) == 1314:
                self.skipTest("Windows symlink creation needs Developer Mode or privileges.")
            raise
        with self.assertRaises(SessionError):
            self.stage()
        self.assertFalse(self.runtime.exists())

    @unittest.skipUnless(os.name == "nt", "Windows junction test")
    def test_junctions_are_rejected_without_following_the_target(self):
        outside = self.root / "outside-junction"
        outside.mkdir()
        (outside / "private.psm").write_bytes(b"not part of the selected design")
        link = self.project / "junction"
        quote = lambda path: "'" + str(path).replace("'", "''") + "'"
        command = f"New-Item -ItemType Junction -Path {quote(link)} -Target {quote(outside)} -ErrorAction Stop | Out-Null"
        result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        try:
            with self.assertRaises(SessionError):
                self.stage()
            self.assertFalse(self.runtime.exists())
            self.assertEqual((outside / "private.psm").read_bytes(), b"not part of the selected design")
        finally:
            os.rmdir(link)

    def test_cli_reports_staged_files_without_constructing_an_editor_session(self):
        self.add("cap.psm")
        output = io.StringIO()
        with patch("orcad_placement_agent.cli.Session", side_effect=AssertionError("No native session needed")):
            with contextlib.redirect_stdout(output):
                result = main(["stage", str(self.board), "--runtime-dir", str(self.runtime),
                               "--model", "managed-board-v1", "--json"])
        self.assertEqual(result, 0)
        data = json.loads(output.getvalue())
        self.assertEqual(data["copy_mode"], "design-folder")
        self.assertFalse(data["native_board_operations"])
        self.assertEqual(data["design_copy"]["library_files"]["packages"], 1)
        self.assertEqual(data["design_copy"]["file_count"], 2)
        self.assertEqual(Path(data["working_board"]).name, "working.brd")

    def test_cli_board_only_mode_is_explicit_in_output(self):
        self.add("cap.psm")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = main(["stage", str(self.board), "--runtime-dir", str(self.runtime),
                           "--board-only", "--json"])
        self.assertEqual(result, 0)
        data = json.loads(output.getvalue())
        self.assertEqual(data["copy_mode"], "board-only")
        self.assertIsNone(data["design_copy"])


if __name__ == "__main__":
    unittest.main()
