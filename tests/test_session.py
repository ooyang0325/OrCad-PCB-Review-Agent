from dataclasses import asdict
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from orcad_placement_agent.protocol import ProtocolError, Request, encode_rows
from orcad_placement_agent.session import Session, SessionError, stage_session, write_json, write_new
from orcad_placement_agent.transport import EditorWindow, IndeterminateDelivery, TransportError


EDITOR = EditorWindow(123, 456, 789, r"C:\Cadence\allegro.exe", "Dedicated board")


class FakeTransport:
    def __init__(self, root):
        self.root = root
        self.nonce = ""
        self.mode = "ok"
        self.sent = 0

    def response(self, identifier):
        return encode_rows([
            ("OPA", "1", self.nonce, identifier, "snapshot"),
            ("message", "Read complete"), ("board", str(self.root / "working.brd")),
            ("scene", "fixture"), ("end", identifier),
        ])

    def send(self, editor, command, request_id, timeout_ms):
        self.sent += 1
        if self.mode == "identity":
            raise TransportError("Identity changed before dispatch")
        if self.mode == "timeout":
            raise IndeterminateDelivery("Unknown dispatch")
        if self.mode == "no_result":
            return
        payload = self.response(request_id)
        if self.mode == "wrong_session":
            payload = payload.replace(self.nonce.encode(), b"f" * 32)
        write_new(self.root / f"{request_id}.result.csv", payload)


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.source = base / "source.brd"
        self.source.write_bytes(b"synthetic non-native test input")
        skill = base / "skill"
        skill.mkdir()
        for name in ("adapter.il", "protocol.il", "placement.il"):
            (skill / name).write_text("; original test placeholder\n", encoding="ascii")
        self.root = stage_session(self.source, base / "runtime", skill)
        self.transport = FakeTransport(self.root)
        self.time = 0.0

        def sleep(seconds):
            self.time += seconds

        self.session = Session(
            self.root, self.transport, clock=lambda: self.time, sleep=sleep
        )
        self.transport.nonce = self.session.nonce

    def request(self):
        return Request(self.session.nonce, "a" * 32, "snapshot")

    def test_stages_a_copy_without_overwriting_source(self):
        self.assertEqual(
            (self.root / "working.brd").read_bytes(), self.source.read_bytes()
        )
        self.assertNotEqual(self.source, self.root / "working.brd")
        self.session.verify_source()

    def test_attach_requires_matching_nonce_and_board(self):
        result = self.session.bind(EDITOR)
        self.assertEqual(result.status, "snapshot")
        self.assertEqual(self.session.editor(), EDITOR)
        with self.assertRaises(SessionError):
            self.session.bind(EDITOR)

    def test_request_receipt_clears_pending_only_after_completion(self):
        result = self.session.exchange(self.request(), EDITOR)
        self.assertEqual(result.status, "snapshot")
        self.assertFalse((self.root / "pending.json").exists())
        self.assertTrue((self.root / ("a" * 32 + ".receipt.json")).exists())

    def test_dispatch_uses_the_same_bounded_total_deadline_as_receipt_waiting(self):
        def send(*_args, **options):
            self.assertEqual(options["timeout_ms"], 60000)
            self.time += 60

        with patch.object(self.transport, "send", side_effect=send):
            with self.assertRaises(IndeterminateDelivery):
                self.session.exchange(self.request(), EDITOR, timeout=60)
        self.assertEqual(self.time, 60)
        self.assertTrue((self.root / "pending.json").is_file())

    def test_duplicate_request_is_never_dispatched_twice(self):
        self.session.exchange(self.request(), EDITOR)
        with self.assertRaises(FileExistsError):
            self.session.exchange(self.request(), EDITOR)
        self.assertEqual(self.transport.sent, 1)

    def test_partial_or_old_receipt_cannot_clear_uncertainty(self):
        self.transport.mode = "wrong_session"
        with self.assertRaises(ProtocolError):
            self.session.exchange(self.request(), EDITOR)
        self.assertTrue((self.root / "pending.json").exists())
        self.assertFalse((self.root / ".inflight").exists())

    def test_timeout_is_durable_and_blocks_new_requests(self):
        self.transport.mode = "no_result"
        with self.assertRaises(IndeterminateDelivery):
            self.session.exchange(self.request(), EDITOR, timeout=0.1)
        with self.assertRaises(SessionError):
            self.session.exchange(
                Request(self.session.nonce, "b" * 32, "snapshot"), EDITOR
            )
        self.assertEqual(self.transport.sent, 1)
        with self.assertRaises(IndeterminateDelivery):
            self.session.reconcile()

    def test_late_receipt_can_be_reconciled_without_replay(self):
        self.transport.mode = "timeout"
        with self.assertRaises(IndeterminateDelivery):
            self.session.exchange(self.request(), EDITOR)
        write_new(
            self.root / ("a" * 32 + ".result.csv"), self.transport.response("a" * 32)
        )
        self.assertEqual(self.session.reconcile().status, "snapshot")
        self.assertEqual(self.transport.sent, 1)
        self.assertFalse((self.root / "pending.json").exists())

    def test_scoped_reconciliation_rechecks_identity_and_operation_under_lock(self):
        self.transport.mode = "timeout"
        with self.assertRaises(IndeterminateDelivery):
            self.session.exchange(self.request(), EDITOR)
        write_new(
            self.root / ("a" * 32 + ".result.csv"), self.transport.response("a" * 32)
        )
        for request_id, operation in [("b" * 32, "snapshot"), ("a" * 32, "apply")]:
            with self.assertRaises(SessionError):
                self.session.reconcile(
                    expected_request_id=request_id, expected_operation=operation
                )
            self.assertTrue((self.root / "pending.json").exists())
        self.assertEqual(
            self.session.reconcile(
                expected_request_id="a" * 32, expected_operation="snapshot"
            ).status, "snapshot"
        )
        self.assertEqual(self.transport.sent, 1)

    def test_rejected_window_identity_is_not_an_unresolved_operation(self):
        self.transport.mode = "identity"
        with self.assertRaises(TransportError):
            self.session.exchange(self.request(), EDITOR)
        self.assertFalse((self.root / "pending.json").exists())

    def test_modified_source_blocks_requests(self):
        self.source.write_bytes(b"changed")
        with self.assertRaises(SessionError):
            self.session.exchange(self.request(), EDITOR)
        self.assertEqual(self.transport.sent, 0)

    def test_native_cannot_silently_enable_unverified_3d_for_a_strict_session(self):
        def response(request_id):
            return encode_rows([
                ("OPA", "1", self.session.nonce, request_id, "snapshot"),
                ("message", "Wrong native policy"),
                ("attachment-policy", "allow-unverified-embedded-3d-v1"),
                ("attachment-unverified", "3D:example.stp/ACIS"), ("end", request_id),
            ])

        with patch.object(self.transport, "response", side_effect=response):
            with self.assertRaisesRegex(ProtocolError, "operator choice"):
                self.session.exchange(self.request(), EDITOR)
        self.assertTrue((self.root / "pending.json").is_file())

    def test_unverified_library_outcome_blocks_writes_but_allows_readback(self):
        digest = "c" * 64
        write_json(self.root / f"library-approval-{digest}.json", {
            "proposal": digest, "request_id": "d" * 32, "confirmation": f"LOAD {digest}",
        })
        with self.assertRaisesRegex(SessionError, "asset-lock continuity"):
            self.session.exchange(Request(self.session.nonce, "e" * 32, "apply", "f" * 32,
                                          "R1", "12", "12", "90"), EDITOR)
        self.assertEqual(self.transport.sent, 0)
        self.assertEqual(self.session.exchange(self.request(), EDITOR).status, "snapshot")

    def test_lock_prevents_concurrent_exchange(self):
        (self.root / ".inflight").mkdir()
        with self.assertRaises(SessionError):
            self.session.exchange(self.request(), EDITOR)
        self.assertEqual(self.transport.sent, 0)

    def test_atomic_publish_never_replaces_existing_content(self):
        path = self.root / "existing"
        write_new(path, b"first")
        with self.assertRaises(FileExistsError):
            write_new(path, b"second")
        self.assertEqual(path.read_bytes(), b"first")


if __name__ == "__main__":
    unittest.main()
