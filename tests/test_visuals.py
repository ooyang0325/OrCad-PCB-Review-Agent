from dataclasses import replace
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch
import zlib

from orcad_placement_agent.protocol import Receipt
from orcad_placement_agent.session import write_json
from orcad_placement_agent.transport import EditorWindow
from orcad_placement_agent.visuals import (
    VisualError, WindowImage, bounded_capture, capture_observation,
    encode_png, png_dimensions,
)


EDITOR = EditorWindow(123, 456, 134334796530859671, r"C:\Cadence\allegro.exe", "Fixture")
PIXELS = bytes([0, 0, 255, 0, 0, 255, 0, 0, 255, 0, 0, 0, 255, 255, 255, 0])


class FakeSession:
    nonce = "a" * 32

    def __init__(self, root):
        self.root = root
        self.working = root / "working.brd"
        self.requests = []
        self.changed = False
        self.reject = False

    def editor(self):
        return EDITOR

    def exchange(self, request):
        self.requests.append(request)
        scene = "changed" if self.changed and len(self.requests) > 1 else "original"
        receipt = Receipt(
            self.nonce, request.request_id, "rejected" if self.reject else "snapshot", "Read",
            (("board", str(self.working)), ("scene", scene), ("snapshot", request.request_id)),
        )
        write_json(self.root / f"{request.request_id}.receipt.json", receipt.to_dict())
        return receipt


class VisualTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.session = FakeSession(self.root)
        self.image = WindowImage(2, 2, encode_png(2, 2, PIXELS))
        self.capture = Mock(return_value=self.image)
        self.prepare = Mock(return_value="b" * 32)

    def observe(self, inspect=None):
        return capture_observation(
            self.session, capture=self.capture,
            inspect_window=inspect or (lambda _hwnd: EDITOR),
            prepare_view=self.prepare,
        )

    def test_observation_publishes_matching_image_and_native_receipts(self):
        observation = self.observe()
        self.assertEqual(observation["kind"], "pcb-visual-observation")
        self.assertEqual(observation["scene_native"], "original")
        self.assertEqual(observation["view_fit_request_id"], "b" * 32)
        self.assertEqual(Path(observation["image_path"]).read_bytes(), self.image.png)
        self.assertEqual(
            json.loads(Path(observation["metadata_path"]).read_text(encoding="utf-8")), observation
        )
        self.assertNotEqual(observation["before_request_id"], observation["after_request_id"])
        self.assertEqual(len(self.session.requests), 2)
        self.assertTrue(all(request.operation == "snapshot" for request in self.session.requests))
        self.capture.assert_called_once_with(EDITOR)
        self.prepare.assert_called_once_with(self.session)

    def test_changed_scene_does_not_publish_visual_success(self):
        self.session.changed = True
        with self.assertRaisesRegex(VisualError, "state changed"):
            self.observe()
        self.assertEqual(list(self.root.glob("visual-*")), [])

    def test_rejected_native_snapshot_prevents_capture(self):
        self.session.reject = True
        with self.assertRaisesRegex(VisualError, "pre-capture"):
            self.observe()
        self.capture.assert_not_called()
        self.prepare.assert_not_called()

    def test_wrong_initial_window_does_not_even_snapshot(self):
        with self.assertRaisesRegex(VisualError, "identity changed"):
            self.observe(lambda _hwnd: replace(EDITOR, pid=999))
        self.assertEqual(self.session.requests, [])
        self.capture.assert_not_called()

    def test_window_reuse_during_capture_is_rejected(self):
        identities = iter([EDITOR, replace(EDITOR, started=1)])
        with self.assertRaisesRegex(VisualError, "changed during"):
            self.observe(lambda _hwnd: next(identities))
        self.assertEqual(list(self.root.glob("visual-*")), [])

    def test_capture_failure_does_not_publish_artifacts(self):
        self.capture.side_effect = VisualError("Window minimized or unavailable")
        with self.assertRaises(VisualError):
            self.observe()
        self.assertEqual(list(self.root.glob("visual-*")), [])

    def test_fit_failure_prevents_a_misleading_capture(self):
        self.prepare.side_effect = VisualError("No fit receipt")
        with self.assertRaises(VisualError):
            self.observe()
        self.capture.assert_not_called()

    def test_image_dimension_mismatch_is_rejected(self):
        self.capture.return_value = WindowImage(3, 2, self.image.png)
        with self.assertRaisesRegex(VisualError, "dimensions disagree"):
            self.observe()

    def test_metadata_write_failure_removes_only_its_new_image(self):
        original = self.root / "unrelated.png"
        original.write_bytes(b"preserve")
        with patch("orcad_placement_agent.visuals.write_json", side_effect=OSError("Disk full")):
            with self.assertRaises(OSError):
                self.observe()
        self.assertEqual(original.read_bytes(), b"preserve")
        self.assertEqual(list(self.root.glob("visual-*")), [])


class PNGTests(unittest.TestCase):
    def test_png_has_correct_dimensions_and_rgb_channels(self):
        png = encode_png(2, 2, PIXELS)
        self.assertEqual(png_dimensions(png), (2, 2))
        cursor = 8
        compressed = b""
        while cursor < len(png):
            size = struct.unpack(">I", png[cursor:cursor + 4])[0]
            if png[cursor + 4:cursor + 8] == b"IDAT":
                compressed += png[cursor + 8:cursor + 8 + size]
            cursor += size + 12
        self.assertEqual(
            zlib.decompress(compressed),
            bytes([0, 255, 0, 0, 0, 255, 0, 0, 0, 0, 255, 255, 255, 255]),
        )

    def test_invalid_sizes_and_incomplete_png_fail_explicitly(self):
        for dimensions, pixels in [((0, 1), b""), ((8193, 1), b""), ((2, 2), b"short")]:
            with self.assertRaises(VisualError):
                encode_png(*dimensions, pixels)
        with self.assertRaises(VisualError):
            png_dimensions(encode_png(2, 2, PIXELS)[:-1])

    def test_capture_worker_timeout_is_bounded_without_stopping_cadence(self):
        with patch(
            "orcad_placement_agent.visuals.subprocess.run",
            side_effect=subprocess.TimeoutExpired("owned capture worker", 12),
        ) as run:
            with self.assertRaisesRegex(VisualError, "isolated capture worker"):
                bounded_capture(EDITOR)
        self.assertEqual(run.call_args.kwargs["timeout"], 12)
        self.assertEqual(run.call_args.args[0][1:],
                         ["-I", "-X", "utf8", "-m", "orcad_placement_agent.visuals", "_capture"])

    def test_worker_failure_and_invalid_output_do_not_become_images(self):
        for code, data in [(2, b""), (0, b"not an image")]:
            with patch(
                "orcad_placement_agent.visuals.subprocess.run",
                return_value=subprocess.CompletedProcess([], code, data, b"Capture unavailable"),
            ):
                with self.assertRaises(VisualError):
                    bounded_capture(EDITOR)


if __name__ == "__main__":
    unittest.main()
