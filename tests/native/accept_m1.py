"""Opt-in native M1 acceptance. Sends snapshot commands only; never apply/save."""

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import time
import uuid

from orcad_placement_agent.proposals import check_snapshot
from orcad_placement_agent.protocol import Receipt, Request
from orcad_placement_agent.session import Session, file_digest, write_json, write_new
from orcad_placement_agent.transport import WindowsAPI


DIGITS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"


def decode_scene(scene: str) -> tuple[list[str], list]:
    """Decode the native lossless dictionary/DAG without evaluating SKILL atoms."""
    prefix, count_text, body = scene.split(";", 2)
    assert prefix == "OPA-FIXTURE-1"
    count = int(count_text)
    assert 0 < count <= 4096 and len(scene) <= 8192
    cursor = 0

    def count_value() -> int:
        nonlocal cursor
        character = body[cursor]
        cursor += 1
        if character != "~":
            return DIGITS.index(character)
        end = body.index(";", cursor)
        value = int(body[cursor:end])
        cursor = end + 1
        return value

    atoms = []
    previous = ""
    for _ in range(count):
        common = count_value()
        length = count_value()
        assert common <= len(previous) and cursor + length <= len(body)
        atom = previous[:common] + body[cursor:cursor + length]
        cursor += length
        atoms.append(atom)
        previous = atom
    assert len(set(atoms)) == len(atoms) and body[cursor] == ";"
    cursor += 1
    nodes: list[list | None] = []

    def index_value() -> int:
        nonlocal cursor
        start = cursor
        value = 0
        while cursor < len(body) and body[cursor] in DIGITS:
            value = value * 62 + DIGITS.index(body[cursor])
            cursor += 1
        assert cursor > start
        return value

    def node():
        nonlocal cursor
        if body[cursor] == "(":
            cursor += 1
            index = len(nodes)
            nodes.append(None)
            result = []
            while body[cursor] != ")":
                if body[cursor] == ".":
                    cursor += 1
                result.append(node())
            cursor += 1
            nodes[index] = result
            return result
        if body[cursor] == "~":
            cursor += 1
            index = index_value()
            assert index < len(nodes) and nodes[index] is not None
            return nodes[index]
        index = index_value()
        assert index < len(atoms)
        return atoms[index]

    tree = node()
    assert cursor == len(body) and isinstance(tree, list)
    assert not any("dbid:" in atom or "pad:" in atom or "_axlPath@" in atom for atom in atoms)
    return atoms, tree


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True, type=Path)
    parser.add_argument("--pid", required=True, type=int)
    parser.add_argument("--hwnd", required=True, type=int)
    options = parser.parse_args()
    session = Session(options.session)
    api = WindowsAPI()
    editor = api.inspect(options.hwnd)
    assert editor.pid == options.pid, "Explicit editor PID/HWND does not match."
    source_before = file_digest(session.source)
    working_before = file_digest(session.working)
    assert source_before == working_before, "M1 must start from the unchanged source copy."
    cases = []

    def unchanged() -> None:
        assert editor.same_process(api.inspect(options.hwnd))
        session.verify_source()
        assert file_digest(session.working) == working_before

    if (session.root / "editor.json").exists():
        assert session.editor().same_process(editor)
        first = session.exchange(Request(session.nonce, uuid.uuid4().hex, "snapshot"))
    else:
        first = session.bind(editor)
    assert first.status == "snapshot"
    assert Path(first.one("board")[1]).resolve() == session.working
    components = check_snapshot(first)
    assert set(components) == {"R1", "R2", "R3"}
    assert first.one("units")[1:] == ("millimeters", "4", "10000")
    for index, refdes in enumerate(("R1", "R2", "R3"), 1):
        component = components[refdes]
        assert component.package == "OPA_FIXTURE_TWO_PIN"
        assert (component.x, component.y, component.angle) == (index * 10, 10, 0)
        assert component.placed and not component.mirrored
        assert component.fixed == (refdes == "R3")
    scene = first.one("scene")[1]
    atoms, tree = decode_scene(scene)
    for token in (
        '"common"', '"components"', '"drc"', '"padstack"', '"definition"',
        '"design-modes"', '"design-values"', '"spacing-modes"', '"physical-modes"',
        '"same-net-modes"', '"spacing"', '"physical"', '"same-net"',
        '"assembly-modes"', '"constraint-options"', '"dfa"', '"layer"',
        '"PACKAGE GEOMETRY/PLACE_BOUND_TOP"', '"BOARD GEOMETRY/DESIGN_OUTLINE"',
        '"PACKAGE KEEPIN/ALL"', '"PACKAGE KEEPOUT/TOP"', '"OPA_FIXTURE_SMD"',
        '"TEST_NET"', '"TEST_RETURN"', "Package_to_Package_Spacing",
        "Package_to_Place_Keepin_Spacing", "Package_to_Place_Keepout_Spacing",
    ):
        assert token in atoms, f"Scene omits {token}"
    cases.append({"case": "real-handshake", "request_id": first.request_id, "status": first.status})
    unchanged()

    def rejected(name: str, make_payload, partial: bool = False) -> None:
        identifier = uuid.uuid4().hex
        payload = Request(session.nonce, identifier, "snapshot").encode()
        path = session.root / f"{identifier}.request.csv"
        if partial:
            path = path.with_name(path.name + ".partial")
        write_new(path, make_payload(payload, identifier))
        session.transport.send(editor, "opa_snapshot", identifier)
        result_path = session.root / f"{identifier}.result.csv"
        deadline = time.monotonic() + 10
        while not result_path.exists():
            assert time.monotonic() < deadline, f"No native rejection receipt for {name}"
            time.sleep(0.05)
        result = Receipt.decode(result_path.read_bytes(), session.nonce, identifier)
        assert result.status == "rejected", (name, result.status, result.message)
        cases.append({"case": name, "request_id": identifier, "status": result.status,
                      "message": result.message})
        unchanged()

    rejected("wrong-nonce", lambda p, _: p.replace(session.nonce.encode(), uuid.uuid4().hex.encode()))
    rejected("wrong-header-id", lambda p, i: p.replace(i.encode(), uuid.uuid4().hex.encode(), 1))
    rejected("wrong-footer-id", lambda p, i: p.replace(b"end," + i.encode(), b"end," + uuid.uuid4().hex.encode()))
    rejected("unsupported-version", lambda p, _: p.replace(b"OPA,1,", b"OPA,2,"))
    rejected("operation-mismatch", lambda p, _: p.replace(b",snapshot\n", b",save\n"))
    rejected("snapshot-write-parameters", lambda p, _: p.replace(b"params,,,,,,", b"params,,R1,10,10,0,"))
    rejected("wrong-parameter-count", lambda p, _: p.replace(b"params,,,,,,", b"params,,,,,,,"))
    rejected("missing-footer", lambda p, _: b"\n".join(p.split(b"\n")[:2]) + b"\n")
    rejected("missing-final-newline", lambda p, _: p[:-1])
    rejected("extra-record", lambda p, _: p + b"extra\n")
    rejected("quoted-request", lambda p, _: p.replace(b"OPA,", b'"OPA",', 1))
    rejected("control-character", lambda p, _: p.replace(b"params", b"para\tms"))
    rejected("non-ascii", lambda p, _: p.replace(b"params", b"para\x80ms"))
    rejected("oversized-row", lambda p, _: b"x" * 1025 + b"\n" + p)
    rejected("partial-file-only", lambda p, _: p, partial=True)

    original = session.root / f"{first.request_id}.result.csv"
    original_content = original.read_bytes()
    original_mtime = original.stat().st_mtime_ns
    session.transport.send(editor, "opa_snapshot", first.request_id)
    assert original.read_bytes() == original_content
    assert original.stat().st_mtime_ns == original_mtime
    cases.append({"case": "duplicate-no-overwrite", "request_id": first.request_id, "status": "preserved"})

    before_files = {path.name for path in session.root.iterdir()}
    for invalid in ("deadbeef", "../not-an-id", "F" * 32):
        api.deliver(editor.hwnd, f"opa_snapshot {invalid}".encode("ascii"), 5000)
    assert {path.name for path in session.root.iterdir()} == before_files
    cases.append({"case": "invalid-command-identifiers", "status": "no-files-created"})

    # Exercise repeated real reads and the bounded native snapshot cache.
    snapshots = []
    for _ in range(17):
        result = session.exchange(Request(session.nonce, uuid.uuid4().hex, "snapshot"))
        assert result.status == "snapshot" and result.one("scene")[1] == scene
        snapshots.append(result.request_id)
        unchanged()
    cases.append({"case": "17-repeat-snapshots", "status": "identical-scenes", "request_ids": snapshots})
    report = {
        "schema": 1, "completed_at": datetime.now(timezone.utc).isoformat(),
        "editor": asdict(editor), "session": str(session.root),
        "native_m1_complete": True, "apply_operations_executed": 0, "save_operations_executed": 0,
        "source_safety_sha256": source_before, "working_unchanged": True,
        "scene_characters": len(scene), "scene_atom_count": len(atoms),
        "scene_top_level_records": len(tree), "cases": cases,
    }
    destination = session.root / f"native-m1-{uuid.uuid4().hex}.json"
    write_json(destination, report)
    print(f"M1 passed: {len(cases)} cases; {len(snapshots) + 1} real snapshots; no apply/save.")
    print(destination)


if __name__ == "__main__":
    main()
