"""Strict, versioned CSV messages shared with the SKILL adapter."""

import csv
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import hashlib
import io
import json
import re
from typing import Iterable


MAX_BYTES = 1024 * 1024
MAX_ROWS = 4096
MAX_FIELD = 8192
ID_PATTERN = re.compile(r"[0-9a-f]{32}")
NUMBER_PATTERN = re.compile(r"-?(?:0|[1-9][0-9]{0,8})(?:\.[0-9]{1,9})?")
STATUSES = frozenset({"snapshot", "applied", "rejected", "rolled_back", "saved", "indeterminate"})
OPERATIONS = frozenset({"snapshot", "apply", "save"})


class ProtocolError(ValueError):
    """Input is incomplete, unsupported, or inconsistent with its schema."""


def identifier(value: str) -> str:
    if not isinstance(value, str) or ID_PATTERN.fullmatch(value) is None:
        raise ProtocolError("Expected a 32-character lowercase hexadecimal ID.")
    return value


def number(value: str) -> Decimal:
    if not isinstance(value, str) or NUMBER_PATTERN.fullmatch(value) is None:
        raise ProtocolError(f"Invalid finite decimal value: {value!r}.")
    try:
        result = Decimal(value)
    except InvalidOperation as error:
        raise ProtocolError("Invalid decimal value.") from error
    if not result.is_finite():
        raise ProtocolError("Numeric values must be finite.")
    return result


def decimal_text(value: Decimal) -> str:
    result = format(value, "f")
    if "." in result:
        result = result.rstrip("0").rstrip(".")
    result = "0" if result in ("-0", "") else result
    number(result)
    return result


def field(value: str) -> str:
    if not isinstance(value, str) or len(value) > MAX_FIELD:
        raise ProtocolError("Fields must be bounded strings.")
    if any(ord(char) < 32 or ord(char) > 126 for char in value):
        raise ProtocolError("Wire fields must contain printable ASCII only.")
    return value


def encode_rows(rows: Iterable[Iterable[str]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    count = 0
    for row in rows:
        values = tuple(field(value) for value in row)
        if not values or len(values) > 16:
            raise ProtocolError("Each record requires 1 to 16 fields.")
        writer.writerow(values)
        count += 1
        if count > MAX_ROWS or output.tell() > MAX_BYTES:
            raise ProtocolError("Message exceeds the protocol size limit.")
    return output.getvalue().encode("ascii")


def decode_rows(payload: bytes) -> tuple[tuple[str, ...], ...]:
    if not payload or len(payload) > MAX_BYTES or not payload.endswith(b"\n"):
        raise ProtocolError("Missing, oversized, or incomplete message.")
    try:
        text = payload.decode("ascii")
        rows = tuple(
            tuple(field(value) for value in row)
            for row in csv.reader(io.StringIO(text, newline=""), strict=True)
        )
    except (UnicodeDecodeError, csv.Error) as error:
        raise ProtocolError("Malformed CSV or non-ASCII message.") from error
    if len(rows) > MAX_ROWS or any(not row or len(row) > 16 for row in rows):
        raise ProtocolError("Invalid record count or field count.")
    return rows


@dataclass(frozen=True)
class Request:
    nonce: str
    request_id: str
    operation: str
    snapshot_id: str = ""
    refdes: str = ""
    x: str = ""
    y: str = ""
    angle: str = ""
    destination: str = ""

    def encode(self) -> bytes:
        identifier(self.nonce)
        identifier(self.request_id)
        if self.operation not in OPERATIONS:
            raise ProtocolError("Unsupported operation.")
        if self.operation == "snapshot":
            if any((self.snapshot_id, self.refdes, self.x, self.y, self.angle, self.destination)):
                raise ProtocolError("Snapshot requests cannot carry write parameters.")
        else:
            identifier(self.snapshot_id)
            if self.operation == "apply":
                if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,30}", self.refdes) is None:
                    raise ProtocolError("Unsupported reference designator.")
                for value in (self.x, self.y, self.angle):
                    number(value)
                if self.destination:
                    raise ProtocolError("Apply cannot include a save destination.")
            elif (
                any((self.refdes, self.x, self.y, self.angle))
                or re.fullmatch(r"revision-[0-9a-f]{32}\.brd", self.destination) is None
            ):
                raise ProtocolError("Save requires only a managed new-revision filename.")
        return encode_rows([
            ("OPA", "1", self.nonce, self.request_id, self.operation),
            ("params", self.snapshot_id, self.refdes, self.x, self.y, self.angle, self.destination),
            ("end", self.request_id),
        ])


@dataclass(frozen=True)
class Receipt:
    nonce: str
    request_id: str
    status: str
    message: str
    records: tuple[tuple[str, ...], ...]

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "Receipt":
        if (
            not isinstance(data, dict)
            or set(data) != {"nonce", "request_id", "status", "message", "records"}
            or not isinstance(data["records"], list)
            or any(not isinstance(row, list) for row in data["records"])
        ):
            raise ProtocolError("Invalid saved receipt schema.")
        return cls.decode(
            encode_rows([
                ["OPA", "1", data["nonce"], data["request_id"], data["status"]],
                ["message", data["message"]], *data["records"],
                ["end", data["request_id"]],
            ]),
            data["nonce"], data["request_id"],
        )

    @classmethod
    def decode(cls, payload: bytes, nonce: str, request_id: str) -> "Receipt":
        identifier(nonce)
        identifier(request_id)
        rows = decode_rows(payload)
        if len(rows) < 3 or rows[0][:4] != ("OPA", "1", nonce, request_id):
            raise ProtocolError("Receipt belongs to a different session or request.")
        if len(rows[0]) != 5 or rows[0][4] not in STATUSES:
            raise ProtocolError("Unsupported receipt status.")
        if rows[-1] != ("end", request_id):
            raise ProtocolError("Receipt completion marker is missing or stale.")
        if len(rows[1]) != 2 or rows[1][0] != "message":
            raise ProtocolError("Receipt must include an explicit message.")
        records = rows[2:-1]
        allowed = {"board": 2, "units": 4, "version": 2, "component": 9,
                   "scene": 2, "snapshot": 2, "saved": 2}
        for record in records:
            if record[0] not in allowed or len(record) != allowed[record[0]]:
                raise ProtocolError("Unsupported receipt record.")
        return cls(nonce, request_id, rows[0][4], rows[1][1], records)

    def to_dict(self) -> dict[str, object]:
        return {
            "nonce": self.nonce, "request_id": self.request_id,
            "status": self.status, "message": self.message,
            "records": [list(row) for row in self.records],
        }

    def one(self, name: str) -> tuple[str, ...]:
        matches = [row for row in self.records if row[0] == name]
        if len(matches) != 1:
            raise ProtocolError(f"Expected exactly one {name} record.")
        return matches[0]

    @property
    def scene_digest(self) -> str:
        self.one("scene")
        return hashlib.sha256(encode_rows(sorted(self.records))).hexdigest()


def canonical_digest(value: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()
