"""Synthetic approval/asset tests; never native Cadence execution."""

import json
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from orcad_placement_agent.agent_tools import AgentActions
from orcad_placement_agent.library_load import (
    _unchanged_cache, approve_libraries, library_status, load_library_proposal, pinned_library_bundle,
    prepare_libraries, setup_inventory,
)
from orcad_placement_agent.protocol import ProtocolError, Receipt, Request, encode_rows
from orcad_placement_agent.proposals import propose
from orcad_placement_agent.save_proposals import prepare_save
from orcad_placement_agent.session import Session, SessionError, stage_session, write_json
from orcad_placement_agent.transport import IndeterminateDelivery
from orcad_placement_agent.visuals import VisualError, WindowImage, capture_observation, encode_png
from tests.test_session import EDITOR


def library_snapshot(session, *, existing=(), placed="0"):
    return Receipt(session.nonce, "2" * 32, "snapshot", "Library setup only", (
        ("board", str(session.working)), ("units", "millimeters", "4", "10000"),
        ("version", "25.1"), ("model", "library-setup-v1"),
        ("snapshot", "2" * 32), ("scene", "OPA-BOARD-1;library-setup-" + ",".join(existing)),
        ("component", "U1", "PART_A", "0", "0", "0", "0", "0", placed),
        ("component", "U2", "PART_B", "0", "0", "0", "0", "0", "0"),
        ("logical-pin", "U1", "1", "SIGNAL"), ("logical-pin", "U2", "1", "SIGNAL"),
        ("definition", "FLASH", "AB00"), ("padstack", "VIA"),
        *(("definition", "PACKAGE", name) for name in existing),
    ))


class LibraryLoadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self.source = self.project / "source.brd"
        self.source.write_bytes(b"Original synthetic staged board")
        for name in ("part_a.psm", "part_b.psm", "pin.pad", "ab00.fsm", "unused.psm"):
            (self.project / name).write_bytes(("original test " + name).encode("ascii"))
        skill = self.root / "skill"
        skill.mkdir()
        for name in ("adapter.il", "placement.il", "protocol.il", "managed_board.il", "library_setup.il"):
            (skill / name).write_text("; original synthetic test placeholder", encoding="ascii")
        self.skill = skill
        self.session = Session(stage_session(self.source, self.root / "sessions", skill, model="managed-board-v1"))
        self.snapshot = library_snapshot(self.session)

    def test_prepare_copies_exact_staged_libraries_without_loading_or_placing(self):
        before = {path.name: path.read_bytes() for path in self.project.iterdir()}
        digest, proposal = prepare_libraries(self.session, self.snapshot)
        self.assertEqual(proposal["packages"], ["PART_A", "PART_B"])
        self.assertEqual({item["filename"] for item in proposal["assets"]},
                         {"part_a.psm", "part_b.psm", "pin.pad", "ab00.fsm"})
        self.assertNotIn("unused.psm", {item["filename"] for item in proposal["assets"]})
        self.assertEqual(load_library_proposal(self.session, digest), proposal)
        with pinned_library_bundle(self.session, proposal):
            pass
        self.assertEqual(library_status(self.session, digest)["status"], "not_dispatched")
        self.assertFalse(list(self.session.root.glob("library-approval-*")))
        self.assertEqual(before, {path.name: path.read_bytes() for path in self.project.iterdir()})

    def test_setup_inventory_is_distinct_from_placement_and_save_authority(self):
        inventory = setup_inventory(self.snapshot)
        self.assertEqual(inventory["existing_padstacks"], ["via"])
        self.assertEqual(inventory["missing_packages"], ["PART_A", "PART_B"])
        with self.assertRaises(ProtocolError):
            propose(self.session, self.snapshot, "U1", "10", "10", "0")
        with self.assertRaises(ProtocolError):
            prepare_save(self.session, self.snapshot)
        with self.assertRaises(ProtocolError):
            setup_inventory(library_snapshot(self.session, placed="1"))
        with self.assertRaises(SessionError):
            prepare_libraries(self.session, library_snapshot(self.session, existing=("PART_A", "PART_B")))
        setup_inventory(replace(self.snapshot, records=(*self.snapshot.records, ("definition", "FORMAT", "TITLE"))))

    def test_unverified_3d_is_explicit_narrow_and_not_a_library_preservation_claim(self):
        native = (*self.snapshot.records,
                  ("attachment-policy", "allow-unverified-embedded-3d-v1"),
                  ("attachment-unverified", "3D:example.stp/ACIS"))
        receipt = replace(self.snapshot, records=native)
        self.assertEqual(setup_inventory(receipt)["unverified_3d_attachments"], ["3D:example.stp/ACIS"])
        self.assertIn("No 3D preservation", receipt.attachment_warning)
        for records in (
            (*self.snapshot.records, ("attachment-unverified", "3D:example.stp/ACIS")),
            (*native, ("attachment-unverified", "DBAttachFile")),
            (*native, ("attachment-unverified", "3D:example.stp/ACIS")),
        ):
            with self.assertRaises(ProtocolError):
                setup_inventory(replace(self.snapshot, records=records))

    def test_missing_conflicting_or_modified_assets_block_preparation(self):
        (self.session.root / "design-data" / "part_a.psm").write_bytes(b"changed")
        with self.assertRaises(SessionError):
            prepare_libraries(self.session, self.snapshot)
        conflict = self.project / "other"
        conflict.mkdir()
        (conflict / "part_a.psm").write_bytes(b"different geometry")
        alternate = Session(stage_session(self.source, self.root / "sessions", self.skill, model="managed-board-v1"))
        with self.assertRaisesRegex(SessionError, "Conflicting"):
            prepare_libraries(alternate, library_snapshot(alternate))
        (self.project / "part_b.psm").unlink()
        (conflict / "part_a.psm").unlink()
        missing = Session(stage_session(self.source, self.root / "sessions", self.skill, model="managed-board-v1"))
        with self.assertRaisesRegex(SessionError, "absent"):
            prepare_libraries(missing, library_snapshot(missing))

    def test_cache_and_control_changes_cannot_reuse_an_approval(self):
        digest, proposal = prepare_libraries(self.session, self.snapshot)
        cached = self.session.root / f"library-{proposal['cache_id']}" / "part_a.psm"
        cached.write_bytes(b"changed")
        with patch.object(self.session, "exchange") as native:
            with self.assertRaises((ProtocolError, SessionError)):
                approve_libraries(self.session, digest, f"LOAD {digest}")
        native.assert_not_called()
        self.assertFalse((self.session.root / f"library-approval-{digest}.json").exists())
        digest, proposal = prepare_libraries(self.session, self.snapshot)
        control = self.session.root / f"library-{proposal['cache_id']}.csv"
        control.write_bytes(control.read_bytes().replace(b"PART_A", b"PART_C"))
        with patch.object(self.session, "exchange") as native:
            with self.assertRaisesRegex(ProtocolError, "control file changed"):
                approve_libraries(self.session, digest, f"LOAD {digest}")
        native.assert_not_called()

    def test_exact_approval_is_separate_single_use_and_confirmed_after_return(self):
        digest, _ = prepare_libraries(self.session, self.snapshot)
        calls = []

        def exchange(request, **_options):
            calls.append(request)
            receipt = Receipt(self.session.nonce, request.request_id, "libraries_loaded", "Fake library load",
                              (*library_snapshot(self.session, existing=("PART_A", "PART_B")).records,
                               ("library-loaded", "PART_A"), ("library-loaded", "PART_B")))
            write_json(self.session.root / f"{request.request_id}.receipt.json", receipt.to_dict())
            return receipt

        with patch.object(self.session, "exchange", side_effect=exchange):
            for answer in ("", "yes", f"APPLY {digest}", f"SAVE {digest}"):
                with self.assertRaises(SessionError):
                    approve_libraries(self.session, digest, answer)
            result = approve_libraries(self.session, digest, f"LOAD {digest}")
            self.assertEqual(result.status, "libraries_loaded")
            with self.assertRaises(FileExistsError):
                approve_libraries(self.session, digest, f"LOAD {digest}")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].operation, "load_libraries")
        status = library_status(self.session, digest)
        self.assertEqual(status["status"], "libraries_loaded")
        self.assertFalse(status["placement_ready"])
        self.assertFalse(status["saved"])

    def test_partial_native_inventory_is_reported_without_claiming_readiness(self):
        digest, _ = prepare_libraries(self.session, self.snapshot)

        def exchange(request, **_options):
            receipt = Receipt(self.session.nonce, request.request_id, "library_partial", "Fake partial load",
                              (*library_snapshot(self.session, existing=("PART_A",)).records,
                               ("library-loaded", "PART_A"), ("library-missing", "PART_B")))
            write_json(self.session.root / f"{request.request_id}.receipt.json", receipt.to_dict())
            return receipt

        with patch.object(self.session, "exchange", side_effect=exchange):
            approve_libraries(self.session, digest, f"LOAD {digest}")
        status = library_status(self.session, digest)
        self.assertEqual(status["status"], "library_partial")
        self.assertFalse(status["placement_ready"] or status["saved"])

    def test_success_without_complete_definition_readback_cannot_be_certified(self):
        digest, _ = prepare_libraries(self.session, self.snapshot)

        def exchange(request, **_options):
            return Receipt(self.session.nonce, request.request_id, "libraries_loaded", "False success",
                           (*self.snapshot.records, ("library-loaded", "PART_A"), ("library-loaded", "PART_B")))

        with patch.object(self.session, "exchange", side_effect=exchange):
            with self.assertRaisesRegex(ProtocolError, "actual native"):
                approve_libraries(self.session, digest, f"LOAD {digest}")
        self.assertFalse((self.session.root / f"library-verified-{digest}.json").exists())

    def test_cache_monitor_detects_even_a_transient_new_dependency(self):
        cache = self.root / "monitored"
        cache.mkdir()
        with self.assertRaisesRegex(SessionError, "cache changed"):
            with _unchanged_cache(cache):
                unapproved = cache / "unapproved.pad"
                unapproved.write_bytes(b"not approved")
                unapproved.unlink()

    def test_namespace_change_during_load_blocks_all_subsequent_writes(self):
        digest, proposal = prepare_libraries(self.session, self.snapshot)

        def exchange(request, **_options):
            (self.session.root / f"library-{proposal['cache_id']}" / "unexpected.pad").write_bytes(b"new")
            receipt = Receipt(self.session.nonce, request.request_id, "rejected", "Fake no-load result", ())
            write_json(self.session.root / f"{request.request_id}.receipt.json", receipt.to_dict())
            return receipt

        with patch.object(self.session, "exchange", side_effect=exchange):
            with self.assertRaisesRegex(SessionError, "cache changed"):
                approve_libraries(self.session, digest, f"LOAD {digest}")
        self.assertTrue(library_status(self.session, digest)["requires_restaging"])
        with patch.object(self.session, "editor"), patch.object(self.session.transport, "send") as send:
            for operation in ("apply", "save", "load_libraries"):
                params = {"refdes": "U1", "x": "1", "y": "1", "angle": "0"} if operation == "apply" else {
                    "destination": ("revision-" + "4" * 32 + ".brd" if operation == "save" else
                                    "library-" + proposal["cache_id"] + ".csv")}
                with self.subTest(operation=operation), self.assertRaisesRegex(SessionError, "asset-lock continuity"):
                    self.session.exchange(Request(self.session.nonce, "5" * 32, operation, "2" * 32, **params))
            send.assert_not_called()

    def test_timeout_never_promotes_a_late_outcome_without_asset_continuity(self):
        digest, _ = prepare_libraries(self.session, self.snapshot)
        with patch.object(self.session, "exchange", side_effect=IndeterminateDelivery("Native may still be loading")):
            with self.assertRaises(IndeterminateDelivery):
                approve_libraries(self.session, digest, f"LOAD {digest}")
        approval = self.session._read_json(f"library-approval-{digest}.json")
        receipt = Receipt(self.session.nonce, approval["request_id"], "libraries_loaded", "Late fake outcome", ())
        write_json(self.session.root / f"{receipt.request_id}.receipt.json", receipt.to_dict())
        status = library_status(self.session, digest)
        self.assertEqual(status["status"], "indeterminate")
        self.assertEqual(status["native_status"], "libraries_loaded")
        self.assertTrue(status["requires_restaging"])
        self.assertFalse((self.session.root / f"library-verified-{digest}.json").exists())

    def test_native_indeterminate_receipt_is_durable_without_clearing_pending_or_replaying(self):
        digest, proposal = prepare_libraries(self.session, self.snapshot)
        request = "7" * 32
        write_json(self.session.root / f"library-approval-{digest}.json",
                   {"proposal": digest, "request_id": request, "confirmation": f"LOAD {digest}"})
        write_json(self.session.root / "pending.json", {"request_id": request, "operation": "load_libraries"})
        (self.session.root / f"{request}.result.csv").write_bytes(encode_rows([
            ("OPA", "1", self.session.nonce, request, "indeterminate"),
            ("message", "Native post-load preservation failed"), ("end", request),
        ]))
        with patch.object(self.session.transport, "send") as send:
            status = library_status(self.session, digest)
            repeated = library_status(self.session, digest)
        self.assertEqual(status, repeated)
        self.assertTrue(status["requires_restaging"])
        self.assertEqual(status["receipt"]["status"], "indeterminate")
        self.assertTrue((self.session.root / "pending.json").exists())
        self.assertFalse((self.session.root / f"library-verified-{digest}.json").exists())
        send.assert_not_called()

    def test_library_requests_cannot_smuggle_placement_or_arbitrary_paths(self):
        Request(self.session.nonce, "3" * 32, "library_snapshot").encode()
        Request(self.session.nonce, "3" * 32, "load_libraries", "2" * 32,
                destination="library-" + "4" * 32 + ".csv").encode()
        for request in (
            Request(self.session.nonce, "3" * 32, "library_snapshot", refdes="U1"),
            Request(self.session.nonce, "3" * 32, "load_libraries", "2" * 32, destination=r"C:\outside.csv"),
            Request(self.session.nonce, "3" * 32, "load_libraries", "2" * 32, refdes="U1",
                    destination="library-" + "4" * 32 + ".csv"),
        ):
            with self.assertRaises(ProtocolError):
                request.encode()

    def test_setup_bind_visual_prepare_load_and_recovery_through_fake_native_transport(self):
        existing, commands = [], []

        def send(_editor, command, request_id, **_options):
            commands.append(command)
            if command == "opa_load_libraries":
                existing.extend(("PART_A", "PART_B"))
            snapshot = library_snapshot(self.session, existing=existing)
            records = [row for row in snapshot.records if row[0] != "snapshot"]
            if command == "opa_library_snapshot":
                status = "snapshot"
                records.append(("snapshot", request_id))
            else:
                self.assertEqual(command, "opa_load_libraries")
                status = "libraries_loaded"
                records.extend(("library-loaded", name) for name in existing)
            (self.session.root / f"{request_id}.result.csv").write_bytes(encode_rows([
                ("OPA", "1", self.session.nonce, request_id, status),
                ("message", "Synthetic native outcome"), *records, ("end", request_id),
            ]))

        image = WindowImage(1, 1, encode_png(1, 1, bytes([0, 0, 255, 0])))

        def capture(session):
            return capture_observation(session, snapshot_operation="library_snapshot",
                                       capture=lambda _editor: image,
                                       inspect_window=lambda _hwnd: EDITOR, prepare_view=lambda _session: None)

        service = AgentActions(self.session.root.parent, session_factory=lambda _path: self.session,
                               library_capture=capture)
        with patch.object(self.session.transport, "send", side_effect=send):
            self.session.bind(EDITOR, library_setup=True)
            prepared = service.dispatch({"action": "prepare-libraries", "session": self.session.root.name})
            self.assertEqual(prepared["visual"]["inspection_operation"], "library_snapshot")
            self.assertEqual(prepared["packages"], ["PART_A", "PART_B"])
            self.assertIn("part_a.psm", prepared["summary"])
            self.assertEqual(commands, ["opa_library_snapshot"] * 3)
            proposal = prepared["proposal_sha256"]
            service.library_capture = lambda _session: (_ for _ in ()).throw(VisualError("Post-image failed"))
            result = service.dispatch({"action": "load-libraries", "session": self.session.root.name,
                                       "proposal": proposal, "confirmation": f"LOAD {proposal}"})
            self.assertEqual(result["status"], "libraries_loaded")
            self.assertIn("visual_error", result)
            status = service.dispatch({"action": "library-status", "session": self.session.root.name,
                                       "proposal": proposal})
            self.assertEqual(status["status"], "libraries_loaded")
            self.assertFalse(status["placement_ready"] or status["saved"])
            self.assertEqual(commands.count("opa_load_libraries"), 1)


if __name__ == "__main__":
    unittest.main()
