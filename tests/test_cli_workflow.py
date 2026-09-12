import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from orcad_placement_agent.cli import main
from orcad_placement_agent.protocol import Receipt
from orcad_placement_agent.session import SessionError
from orcad_placement_agent.transport import IndeterminateDelivery


class WorkflowCLITests(unittest.TestCase):
    def setUp(self):
        self.session = Mock()
        self.session.nonce = "1" * 32
        self.session.root = Path(r"C:\isolated")
        self.session.working = self.session.root / "working.brd"
        self.session.exchange.return_value = Receipt(
            "1" * 32, "2" * 32, "snapshot", "Read complete",
            (("snapshot", "2" * 32),),
        )

    def run_cli(self, args):
        self.output = io.StringIO()
        self.error = io.StringIO()
        with (
            patch("orcad_placement_agent.cli.Session", return_value=self.session),
            contextlib.redirect_stdout(self.output),
            contextlib.redirect_stderr(self.error),
        ):
            return main(args)

    def test_save_without_exact_confirmation_never_dispatches_save(self):
        with patch("builtins.input", return_value="yes"):
            code = self.run_cli(["save", "--session", r"C:\isolated"])
        self.assertEqual(code, 2)
        self.assertEqual(self.session.exchange.call_count, 1)
        self.assertEqual(self.session.exchange.call_args.args[0].operation, "snapshot")

    def test_save_confirmation_has_one_fresh_managed_destination(self):
        snapshot = self.session.exchange.return_value
        self.session.exchange.side_effect = [
            snapshot, Receipt("1" * 32, "3" * 32, "saved", "Saved", ())
        ]
        with patch("builtins.input", return_value="SAVE " + "2" * 32):
            code = self.run_cli(["save", "--session", r"C:\isolated"])
        self.assertEqual(code, 0)
        request = self.session.exchange.call_args.args[0]
        self.assertEqual(request.operation, "save")
        self.assertEqual(request.snapshot_id, "2" * 32)
        self.assertRegex(request.destination, r"^revision-[0-9a-f]{32}\.brd$")

    def test_no_stdin_cancels_save(self):
        with patch("builtins.input", side_effect=EOFError):
            code = self.run_cli(["save", "--session", r"C:\isolated"])
        self.assertEqual(code, 1)
        self.assertEqual(self.session.exchange.call_count, 1)

    def test_indeterminate_exit_is_not_success_or_automatic_retry(self):
        self.session.exchange.side_effect = IndeterminateDelivery("No receipt")
        code = self.run_cli(["snapshot", "--session", r"C:\isolated"])
        self.assertEqual(code, 3)
        self.assertEqual(self.session.exchange.call_count, 1)
        self.assertIn("INDETERMINATE", self.error.getvalue())

    def test_reconcile_never_sends_another_request(self):
        self.session.reconcile.side_effect = IndeterminateDelivery("Still unknown")
        code = self.run_cli(["reconcile", "--session", r"C:\isolated"])
        self.assertEqual(code, 3)
        self.session.exchange.assert_not_called()

    def test_setup_attach_uses_separate_library_handshake(self):
        self.session.bind.return_value = self.session.exchange.return_value
        with patch("orcad_placement_agent.cli.WindowsAPI") as api:
            code = self.run_cli(["attach", "--session", r"C:\isolated", "--hwnd", "123", "--library-setup"])
        self.assertEqual(code, 0)
        self.session.bind.assert_called_once_with(api.return_value.inspect.return_value, library_setup=True)
        self.assertIn("not yet established", self.output.getvalue())

    def test_noninteractive_library_cli_cannot_request_or_supply_approval(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("orcad_placement_agent.cli.AgentActions") as actions,
            patch("orcad_placement_agent.cli.sys.stdin.isatty", return_value=False),
            patch("builtins.input") as prompt,
        ):
            code = self.run_cli(["libraries", "load", "--session", directory, "--proposal", "a" * 64])
        self.assertEqual(code, 2)
        actions.return_value.dispatch.assert_not_called()
        prompt.assert_not_called()
        self.assertIn("interactive terminal", self.error.getvalue())

    def test_library_post_image_failure_is_not_a_success_exit(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("orcad_placement_agent.cli.AgentActions") as actions,
        ):
            actions.return_value.dispatch.return_value = {
                "status": "libraries_loaded", "visual_error": "Post-image unavailable",
            }
            code = self.run_cli(["libraries", "status", "--session", directory, "--proposal", "a" * 64])
        self.assertEqual(code, 2)
        self.assertIn("libraries_loaded", self.output.getvalue())


if __name__ == "__main__":
    unittest.main()
