import unittest

from orcad_placement_agent.protocol import (
    ProtocolError, Receipt, Request, decode_rows, encode_rows, number,
)


NONCE = "1" * 32
ID = "2" * 32


class ProtocolTests(unittest.TestCase):
    def test_snapshot_request_has_no_write_parameters(self):
        rows = decode_rows(Request(NONCE, ID, "snapshot").encode())
        self.assertEqual(rows[0], ("OPA", "1", NONCE, ID, "snapshot"))
        self.assertEqual(rows[-1], ("end", ID))
        with self.assertRaises(ProtocolError):
            Request(NONCE, ID, "snapshot", x="10").encode()

    def test_apply_requires_explicit_expected_snapshot(self):
        with self.assertRaises(ProtocolError):
            Request(NONCE, ID, "apply", refdes="R1", x="10", y="10", angle="0").encode()
        Request(NONCE, ID, "apply", "3" * 32, "R1", "10", "10", "90").encode()

    def test_file_paths_and_arbitrary_operations_are_not_requests(self):
        for operation, destination in [
            ("eval", ""), ("save", "../source.brd"), ("save", r"C:\source.brd"),
            ("save", "source.brd"),
        ]:
            with self.subTest(operation=operation, destination=destination):
                with self.assertRaises(ProtocolError):
                    Request(NONCE, ID, operation, "3" * 32, destination=destination).encode()

    def test_fields_round_trip_quotes_and_commas_without_evaluation(self):
        rows = (("scene", '("R1", "shape")'),)
        self.assertEqual(decode_rows(encode_rows(rows)), rows)

    def test_invalid_fields_and_partial_messages(self):
        for payload in [b"", b"one,two", b'one,"bad\n', b"one,\xff\n", b"one,\x00\n"]:
            with self.subTest(payload=payload):
                with self.assertRaises(ProtocolError):
                    decode_rows(payload)
        for value in ["one\ntwo", "\u6587\u4ef6", "x" * 9000]:
            with self.assertRaises(ProtocolError):
                encode_rows([["value", value]])

    def test_invalid_numbers_are_not_silently_coerced(self):
        for value in ["nan", "NaN", "inf", "1e100", "", "1;exit()", "1\n", "01", "1."]:
            with self.subTest(value=value):
                with self.assertRaises(ProtocolError):
                    number(value)

    def receipt(self, status="snapshot"):
        return encode_rows([
            ["OPA", "1", NONCE, ID, status], ["message", "Read complete"],
            ["scene", "supported fixture state"], ["end", ID],
        ])

    def test_receipt_binds_session_request_and_terminal_marker(self):
        receipt = Receipt.decode(self.receipt(), NONCE, ID)
        self.assertEqual(receipt.status, "snapshot")
        for nonce, request_id in [("3" * 32, ID), (NONCE, "3" * 32)]:
            with self.assertRaises(ProtocolError):
                Receipt.decode(self.receipt(), nonce, request_id)
        with self.assertRaises(ProtocolError):
            Receipt.decode(self.receipt()[:-5], NONCE, ID)

    def test_unknown_status_rejected(self):
        with self.assertRaises(ProtocolError):
            Receipt.decode(self.receipt("success"), NONCE, ID)

    def test_duplicate_scene_not_a_valid_snapshot(self):
        receipt = Receipt(NONCE, ID, "snapshot", "message", (("scene", "a"), ("scene", "b")))
        with self.assertRaises(ProtocolError):
            _ = receipt.scene_digest


if __name__ == "__main__":
    unittest.main()
