from pathlib import Path
import json
import tempfile
import unittest

from orcad_placement_agent.protocol import ProtocolError, Receipt
from orcad_placement_agent.proposals import (
    approve_and_apply, load_proposal, propose, proposal_summary,
)
from orcad_placement_agent.session import SessionError


class FakeSession:
    nonce = "1" * 32

    def __init__(self, root):
        self.root = root
        self.requests = []

    def _read_json(self, name):
        return json.loads((self.root / name).read_text(encoding="utf-8"))

    def exchange(self, request):
        self.requests.append(request)
        return Receipt(self.nonce, request.request_id, "applied", "Applied", ())


class ProposalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.session = FakeSession(Path(self.temp.name))

    def snapshot(self, *, fixed="0", extra=()):
        return Receipt("1" * 32, "2" * 32, "snapshot", "Read complete", (
            ("snapshot", "2" * 32), ("board", r"C:\fixture\working.brd"),
            ("units", "millimeters", "3", "1000"), ("version", "25.1"),
            ("scene", "all components, bounds, nets and rule settings"),
            ("component", "R1", "fixture", "10", "10", "0", "0", fixed, "1"),
            *extra,
        ))

    def test_target_is_quantized_and_summary_discloses_actual_target(self):
        digest, proposal = propose(self.session, self.snapshot(), "R1", "12.0004", "10", "90")
        self.assertEqual(proposal["x"], "12")
        self.assertIn("memory only", proposal_summary(proposal))
        self.assertEqual(load_proposal(self.session, digest), proposal)

    def test_fixed_missing_noop_and_unsupported_angle_rejected(self):
        cases = [
            (self.snapshot(fixed="1"), "R1", "12", "10", "0"),
            (self.snapshot(), "R2", "12", "10", "0"),
            (self.snapshot(), "R1", "10", "10", "0"),
            (self.snapshot(), "R1", "12", "10", "45"),
        ]
        for args in cases:
            with self.subTest(args=args):
                with self.assertRaises(ProtocolError):
                    propose(self.session, *args)

    def test_other_component_state_is_bound_to_proposal(self):
        first = propose(self.session, self.snapshot(), "R1", "12", "10", "90")[0]
        changed = self.snapshot(extra=(
            ("component", "R2", "fixture", "20", "10", "0", "0", "0", "1"),
        ))
        second = propose(self.session, changed, "R1", "12", "10", "90")[0]
        self.assertNotEqual(first, second)

    def test_duplicate_refdes_is_rejected(self):
        extra = (("component", "R1", "fixture", "20", "10", "0", "0", "0", "1"),)
        with self.assertRaises(ProtocolError):
            propose(self.session, self.snapshot(extra=extra), "R1", "12", "10", "0")

    def test_modified_proposal_cannot_reuse_approval(self):
        digest, proposal = propose(self.session, self.snapshot(), "R1", "12", "10", "0")
        proposal["x"] = "99"
        (self.session.root / f"proposal-{digest}.json").write_text(
            json.dumps(proposal), encoding="utf-8"
        )
        with self.assertRaises(ProtocolError):
            approve_and_apply(self.session, digest, f"APPLY {digest}")
        self.assertEqual(self.session.requests, [])

    def test_confirmation_must_bind_the_entire_proposal(self):
        digest, _ = propose(self.session, self.snapshot(), "R1", "12", "10", "0")
        for confirmation in ["yes", "", f"APPLY {'a' * 64}", f"APPLY {digest}\n"]:
            with self.assertRaises(SessionError):
                approve_and_apply(self.session, digest, confirmation)
        self.assertEqual(self.session.requests, [])

    def test_approved_proposal_can_be_dispatched_only_once(self):
        digest, _ = propose(self.session, self.snapshot(), "R1", "12", "10", "0")
        approve_and_apply(self.session, digest, f"APPLY {digest}")
        with self.assertRaises(FileExistsError):
            approve_and_apply(self.session, digest, f"APPLY {digest}")
        self.assertEqual(len(self.session.requests), 1)
        request = self.session.requests[0]
        self.assertEqual((request.snapshot_id, request.refdes, request.x), ("2" * 32, "R1", "12"))


if __name__ == "__main__":
    unittest.main()
