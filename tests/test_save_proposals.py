import json
from pathlib import Path
import tempfile
import unittest

from orcad_placement_agent.protocol import Receipt
from orcad_placement_agent.save_proposals import prepare_save, approve_save, load_save, save_status
from orcad_placement_agent.session import SessionError
from tests.test_board import managed_snapshot


class SaveProposalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

        class FakeSession:
            nonce = "1" * 32

            def __init__(self, root):
                self.root = root
                self.calls = []

            def _read_json(self, name):
                return json.loads((self.root / name).read_text())

            def exchange(self, request):
                self.calls.append(request)
                path = self.root / request.destination
                path.write_bytes(b"Original simulated saved board")
                receipt = Receipt(self.nonce, request.request_id, "saved", "Fake saved",
                                  (*managed_snapshot().records, ("saved", str(path))))
                (self.root / f"{request.request_id}.receipt.json").write_text(json.dumps(receipt.to_dict()))
                return receipt

        self.session = FakeSession(Path(self.temp.name))

    def test_prepare_is_nonmutating_and_save_needs_separate_exact_approval(self):
        digest, value = prepare_save(self.session, managed_snapshot())
        self.assertEqual(load_save(self.session, digest), value)
        self.assertEqual(save_status(self.session, digest)["status"], "not_dispatched")
        for answer in ("yes", "", f"APPLY {digest}", f"SAVE {digest}\n"):
            with self.assertRaises(SessionError):
                approve_save(self.session, digest, answer)
        self.assertEqual(self.session.calls, [])
        receipt = approve_save(self.session, digest, f"SAVE {digest}")
        self.assertEqual(receipt.status, "saved")
        self.assertEqual(self.session.calls[0].operation, "save")
        status = save_status(self.session, digest)
        self.assertTrue(status["artifact_available"])
        self.assertFalse(status["reopened"])
        with self.assertRaises((FileExistsError, SessionError)):
            approve_save(self.session, digest, f"SAVE {digest}")
        self.assertEqual(len(self.session.calls), 1)

    def test_existing_revision_is_never_overwritten(self):
        digest, value = prepare_save(self.session, managed_snapshot())
        path = self.session.root / value["destination"]
        path.write_bytes(b"Keep this existing revision")
        with self.assertRaises(SessionError):
            approve_save(self.session, digest, f"SAVE {digest}")
        self.assertEqual(path.read_bytes(), b"Keep this existing revision")
        self.assertEqual(self.session.calls, [])


if __name__ == "__main__":
    unittest.main()
