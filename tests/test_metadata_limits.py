"""Wire/JSON expansion boundaries; synthetic data, not native Cadence evidence."""

from pathlib import Path
import tempfile
import unittest

from orcad_placement_agent.advisory import _snapshot_context
from orcad_placement_agent.board import from_receipt
from orcad_placement_agent.protocol import MAX_BYTES, MAX_METADATA_BYTES, Receipt, encode_rows
from orcad_placement_agent.proposals import load_proposal, propose
from orcad_placement_agent.resources import asset_directory
from orcad_placement_agent.save_proposals import load_save, prepare_save
from orcad_placement_agent.session import Session, SessionError, stage_session, write_json


class MetadataLimitTests(unittest.TestCase):
    def test_large_valid_wire_receipt_and_embedded_proposals_remain_readable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.brd"
            source.write_bytes(b"Original synthetic staging bytes; never opened in Cadence")
            session = Session(stage_session(source, root / "sessions", asset_directory("skill"),
                                            model="managed-board-v1"))
            request_id = "2" * 32
            records = [
                ("snapshot", request_id), ("board", str(session.working)),
                ("units", "millimeters", "4", "10000"), ("version", "25.1"),
                ("model", "managed-board-v1"), ("outline", "0", "0", "100", "100"),
                ("keepin", "1", "1", "99", "99"), ("layer", "TOP"), ("layer", "BOTTOM"),
            ]
            for component in range(240):
                refdes = f"U{component}"
                records.extend([
                    ("component", refdes, "original-smd", "0", "0", "0", "0", "0", "0"),
                    ("bounds", refdes, "-1", "-1", "1", "1"),
                ])
                for pin in range(14):
                    records.append(("pin", refdes, str(pin + 1), f"N{component}_{pin}" + "\\" * 80, "0", "0"))
            scene = "OPA-BOARD-1;" + "\\" * 400000
            parts = [scene[index:index + 8192] for index in range(0, len(scene), 8192)]
            records.append(("scene", f"OPA-BOARD-1;chunks={len(parts)}"))
            records.extend(("scene-part", str(index), part) for index, part in enumerate(parts))
            receipt = Receipt(session.nonce, request_id, "snapshot", "Synthetic boundary case", tuple(records))
            rows = [
                ("OPA", "1", session.nonce, request_id, "snapshot"),
                ("message", receipt.message), *records, ("end", request_id),
            ]
            payload = encode_rows(rows)
            self.assertLess(len(payload), MAX_BYTES)
            # Native CSV always quotes every field, unlike Python's minimal quoting.
            native_bytes = sum(len(",".join('"' + field.replace('"', '""') + '"' for field in row)) + 1
                               for row in records)
            self.assertLessEqual(native_bytes, 1032192)
            self.assertLessEqual(len(records), 4088)
            receipt = Receipt.decode(payload, session.nonce, request_id)
            self.assertEqual(len(from_receipt(receipt)["components"]), 240)
            path = session.root / f"{request_id}.receipt.json"
            write_json(path, receipt.to_dict())
            self.assertGreater(path.stat().st_size, MAX_BYTES)
            self.assertLess(path.stat().st_size, MAX_METADATA_BYTES)
            self.assertEqual(Receipt.from_dict(session._read_json(path.name)), receipt)
            self.assertEqual(len(_snapshot_context(path)["components"]), 240)
            digest, proposal = propose(session, receipt, "U0", "10", "10", "0")
            self.assertEqual(load_proposal(session, digest), proposal)
            self.assertGreater((session.root / f"proposal-{digest}.json").stat().st_size, MAX_BYTES)
            digest, save = prepare_save(session, receipt)
            self.assertEqual(load_save(session, digest), save)
            result = {"status": "recorded", "receipt": receipt.to_dict(), "visual": {"scene_native": scene}}
            write_json(session.root / "expanded-result.json", result)
            self.assertEqual(session._read_json("expanded-result.json"), result)

    def test_writer_refuses_unreadable_metadata_before_creating_an_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "oversized.json"
            with self.assertRaises(SessionError):
                write_json(path, {"value": "x" * MAX_METADATA_BYTES})
            self.assertFalse(path.exists())
            self.assertFalse(path.with_name(path.name + ".partial").exists())


if __name__ == "__main__":
    unittest.main()
