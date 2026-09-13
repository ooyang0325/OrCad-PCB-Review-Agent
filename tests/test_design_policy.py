from copy import deepcopy
import unittest

from orcad_placement_agent.design_policy import decode_policy, validate_policy
from orcad_placement_agent.protocol import ProtocolError, Receipt, canonical_digest


MODEL = "grouped-constraints-v1"
REFS = {"U1", "R1", "J1", "C1"}
CHUNKS = ("OPA-BOARD-1;synthetic protected policy;", 'opaque value="0.2000";')
DB_NETS = tuple(f"DB{index}" for index in range(8))
POWER_NETS = tuple(f"P{index}" for index in range(6))
FACTS = (
    ("room", "3_QP", "3", "110", "-80", "150", "-40"),
    ("room", "1_QP", "1", "-120.0000", "-80", "-80.0000", "-40.00"),
    ("room", "2_QP", "2", "70", "-80", "100", "-40"),
    ("room-assignment", "U1", "FUNC_UC", "UC"),
    ("room-assignment", "R1", "", "POWER"),
    ("room-assignment", "J1", "", "SD"),
    ("room-assignment", "C1", "", "LCD"),
    ("room-assignment", "U1", "", "UC"),
    ("net-group", "POWER", "POWER", "POWER", "DEFAULT"),
    ("net-group", "DB", "SIGNAL", "SIGNAL", ""),
    *(("net-group-member", "POWER", name) for name in reversed(POWER_NETS)),
    *(("net-group-member", "DB", name) for name in reversed(DB_NETS)),
    ("constraint-set", "sameNet", "DEFAULT"),
    *(("constraint-set", domain, name) for domain in ("spacing", "physical")
      for name in ("SIGNAL", "POWER", "DEFAULT")),
    *(("policy-net", name) for name in reversed(DB_NETS + POWER_NETS)),
)
COUNT_TAGS = (
    "policy-part", "room", "room-assignment", "net-group",
    "net-group-member", "constraint-set", "policy-net",
)


def receipt(records):
    return Receipt("1" * 32, "2" * 32, "snapshot", "Synthetic policy", tuple(records))


def policy_receipt(facts=FACTS, chunks=CHUNKS):
    parts = tuple(("policy-part", str(index), chunk) for index, chunk in enumerate(chunks))
    rows = (*parts, *facts)
    counts = tuple(str(sum(row[0] == name for row in rows)) for name in COUNT_TAGS)
    return receipt((("policy-model", MODEL), ("policy", *counts), *rows))


def empty_policy():
    return {
        "model": MODEL, "digest": "a" * 64, "rooms": [], "room_assignments": [],
        "net_groups": [], "constraint_sets": {name: ["DEFAULT"] for name in ("physical", "spacing", "sameNet")},
        "nets": [],
    }


def room(name="A", label="1"):
    return {"name": name, "label": label, "bounds": ["0", "0", "1", "1"]}


def group(name="G", nets=()):
    return {"name": name, "physical": "", "spacing": "", "same_net": "", "nets": list(nets)}


class DecodePolicyTests(unittest.TestCase):
    def test_absent_legacy_policy_returns_none(self):
        for rows in ((), (("board", r"C:\isolated\working.brd"), ("scene", "legacy"))):
            with self.subTest(rows=rows):
                self.assertIsNone(decode_policy(receipt(rows), REFS))

    def test_full_wire_decodes_canonically_without_input_mutation(self):
        original = policy_receipt()
        saved = deepcopy(original)
        refs = set(REFS)
        policy = decode_policy(original, refs)
        self.assertEqual(original, saved)
        self.assertEqual(refs, REFS)
        self.assertEqual(policy, {
            "model": MODEL,
            "digest": canonical_digest({"native_policy": "".join(CHUNKS)}),
            "rooms": [
                {"name": "1_QP", "label": "1", "bounds": ["-120", "-80", "-80", "-40"]},
                {"name": "2_QP", "label": "2", "bounds": ["70", "-80", "100", "-40"]},
                {"name": "3_QP", "label": "3", "bounds": ["110", "-80", "150", "-40"]},
            ],
            "room_assignments": [
                {"refdes": "C1", "owner": "", "label": "LCD"},
                {"refdes": "J1", "owner": "", "label": "SD"},
                {"refdes": "R1", "owner": "", "label": "POWER"},
                {"refdes": "U1", "owner": "", "label": "UC"},
                {"refdes": "U1", "owner": "FUNC_UC", "label": "UC"},
            ],
            "net_groups": [
                {"name": "DB", "physical": "SIGNAL", "spacing": "SIGNAL", "same_net": "",
                 "nets": sorted(DB_NETS)},
                {"name": "POWER", "physical": "POWER", "spacing": "POWER", "same_net": "DEFAULT",
                 "nets": sorted(POWER_NETS)},
            ],
            "constraint_sets": {
                "physical": ["DEFAULT", "POWER", "SIGNAL"],
                "spacing": ["DEFAULT", "POWER", "SIGNAL"], "sameNet": ["DEFAULT"],
            },
            "nets": sorted(DB_NETS + POWER_NETS),
        })
        self.assertEqual(policy, decode_policy(policy_receipt(tuple(reversed(FACTS))), refs))

    def test_outside_board_rooms_and_unmatched_tags_are_preserved(self):
        policy = decode_policy(policy_receipt(), REFS)
        self.assertEqual(policy["rooms"][0]["bounds"], ["-120", "-80", "-80", "-40"])
        self.assertEqual({item["label"] for item in policy["rooms"]}, {"1", "2", "3"})
        self.assertEqual({item["label"] for item in policy["room_assignments"]}, {"UC", "POWER", "SD", "LCD"})
        self.assertEqual([item["owner"] for item in policy["room_assignments"] if item["refdes"] == "U1"],
                         ["", "FUNC_UC"])

    def test_synthetic_deleted_room_inventory_preserves_assignments_and_opaque_stackup(self):
        refs = {f"U{index}" for index in range(42)}
        facts = (
            *(row for row in FACTS if row[0] not in {"room", "room-assignment"}),
            *(("policy-net", f"OTHER{index}") for index in range(34)),
            *(("room-assignment", refdes, owner, "UC") for refdes in sorted(refs)
              for owner in ("", f"FUNCTION_{refdes}")),
        )
        chunks = (
            "OPA-BOARD-1;synthetic stackup=TOP,L2,L3,BOTTOM;positive-plane=L2;",
            "synthetic WIRE_PROFILE:TOP=(),L2=(),L3=(),BOTTOM=();named-value=0.2000;",
        )
        original = policy_receipt(facts, chunks)
        self.assertEqual(original.records[1], ("policy", "2", "0", "84", "2", "14", "7", "48"))
        policy = decode_policy(original, refs)
        self.assertEqual(policy["rooms"], [])
        self.assertEqual(len(policy["room_assignments"]), 84)
        self.assertEqual([item["name"] for item in policy["net_groups"]], ["DB", "POWER"])
        self.assertEqual(sum(len(item["nets"]) for item in policy["net_groups"]), 14)
        self.assertEqual(sum(map(len, policy["constraint_sets"].values())), 7)
        self.assertEqual(len(policy["nets"]), 48)
        self.assertEqual(policy, validate_policy(policy, refs))
        self.assertEqual(policy["digest"], canonical_digest({"native_policy": "".join(chunks)}))
        changed = decode_policy(policy_receipt(facts, (chunks[0], chunks[1] + "opaque-change;")), refs)
        self.assertNotEqual(policy.pop("digest"), changed.pop("digest"))
        self.assertEqual(policy, changed)

    def test_ungrouped_room_identifier_does_not_invent_a_net_group(self):
        facts = (
            *(row for row in FACTS if row[0] != "room"),
            ("room", "@ungrouped:UC", "UC", "-120", "-80", "-80", "-40"),
        )
        policy = decode_policy(policy_receipt(facts), REFS)
        self.assertEqual(policy["rooms"], [
            {"name": "@ungrouped:UC", "label": "UC", "bounds": ["-120", "-80", "-80", "-40"]},
        ])
        self.assertEqual([item["name"] for item in policy["net_groups"]], ["DB", "POWER"])
        self.assertEqual(policy, validate_policy(policy, REFS))

    def test_changed_opaque_value_changes_digest_only(self):
        before = decode_policy(policy_receipt(), REFS)
        after = decode_policy(policy_receipt(chunks=(CHUNKS[0], 'opaque value="0.2500";')), REFS)
        self.assertNotEqual(before.pop("digest"), after.pop("digest"))
        self.assertEqual(before, after)

    def test_chunk_boundaries_do_not_change_fingerprint_or_interpret_opaque_text(self):
        text = 'OPA-BOARD-1;opaque("quotes",nil); __import__("not_executed"); axlDBSave("never");'
        single = decode_policy(policy_receipt(chunks=(text,)), REFS)
        split = decode_policy(policy_receipt(chunks=(text[:5], text[5:17], text[17:])), REFS)
        self.assertEqual(single, split)
        self.assertEqual(single["digest"], canonical_digest({"native_policy": text}))

    def test_every_orphan_record_requires_model_and_header(self):
        original = policy_receipt().records
        for row in original:
            with self.subTest(tag=row[0]):
                with self.assertRaises(ProtocolError):
                    decode_policy(receipt((row,)), REFS)
        for missing in ("policy-model", "policy"):
            with self.assertRaises(ProtocolError):
                decode_policy(receipt(row for row in original if row[0] != missing), REFS)

    def test_duplicate_or_unsupported_markers_are_rejected(self):
        original = policy_receipt().records
        for rows in (
            (*original, original[0]), (*original, original[1]),
            (("policy-model", "future"), *original[1:]),
        ):
            with self.assertRaises(ProtocolError):
                decode_policy(receipt(rows), REFS)

    def test_missing_duplicate_reordered_and_gapped_chunks_are_rejected(self):
        original = policy_receipt().records
        for rows in (
            (*original[:3], *original[4:]),
            (*original, original[2]),
            (*original[:2], original[3], original[2], *original[4:]),
            (*original[:3], ("policy-part", "2", CHUNKS[1]), *original[4:]),
            (*original[:3], ("policy-part", "0", CHUNKS[1]), *original[4:]),
            (original[1], original[0], *original[2:]),
            (original[2], *original[:2], *original[3:]),
            (*original[:3], original[4], original[3], *original[5:]),
            (original[4], *original[:4], *original[5:]),
        ):
            with self.subTest(rows=rows[:5]):
                with self.assertRaises(ProtocolError):
                    decode_policy(receipt(rows), REFS)
        for index in ("-1", "+1", "01", "1.0", "1" * 8000):
            with self.subTest(index=index[:10]):
                with self.assertRaises(ProtocolError):
                    decode_policy(receipt((*original[:3], ("policy-part", index, CHUNKS[1]),
                                           *original[4:])), REFS)

    def test_invalid_header_counts_are_rejected_before_integer_conversion(self):
        original = policy_receipt().records
        for column in range(1, 8):
            for value in ("-1", "+1", "01", "1.0", "", " 1", "1 ", "1e1", "1" * 8000, "99999"):
                with self.subTest(column=column, value=value[:10]):
                    header = list(original[1])
                    header[column] = value
                    with self.assertRaises(ProtocolError):
                        decode_policy(receipt((original[0], tuple(header), *original[2:])), REFS)
            header = list(original[1])
            header[column] = str(int(header[column]) + 1)
            with self.subTest(column=column, wrong_count=True):
                with self.assertRaises(ProtocolError):
                    decode_policy(receipt((original[0], tuple(header), *original[2:])), REFS)

    def test_chunks_require_bounded_nonempty_printable_ascii_and_native_prefix(self):
        for chunks in (
            (), ("OPA-BOARD-1;",) * 65, ("",), ("legacy-policy",),
            (CHUNKS[0], ""), (CHUNKS[0], "x" * 8193),
            (CHUNKS[0], "\n"), (CHUNKS[0], "\x7f"), (CHUNKS[0], "\u6587"),
        ):
            with self.subTest(lengths=tuple(map(len, chunks))):
                with self.assertRaises(ProtocolError):
                    decode_policy(policy_receipt(chunks=chunks), REFS)
        chunks = ("OPA-BOARD-1;" + "x" * (8192 - len("OPA-BOARD-1;")),) + ("y" * 8192,) * 63
        result = decode_policy(policy_receipt(chunks=chunks), REFS)
        self.assertEqual(result["digest"], canonical_digest({"native_policy": "".join(chunks)}))

    def test_missing_unknown_duplicate_and_overfull_catalogs_are_rejected(self):
        for facts in (
            tuple(row for row in FACTS if row[0] != "constraint-set"),
            tuple(row for row in FACTS if row[:2] != ("constraint-set", "sameNet")),
            tuple(row for row in FACTS if row != ("constraint-set", "physical", "DEFAULT")),
            (*FACTS, ("constraint-set", "electrical", "DEFAULT")),
            (*FACTS, ("constraint-set", "sameNet", "DEFAULT")),
            (*FACTS, *(("constraint-set", "sameNet", f"C{index}") for index in range(32))),
        ):
            with self.assertRaises(ProtocolError):
                decode_policy(policy_receipt(facts), REFS)

    def test_unknown_memberships_cset_references_and_component_refs_are_rejected(self):
        variants = (
            (*FACTS, ("net-group-member", "unknown", DB_NETS[0])),
            (*FACTS, ("net-group-member", "DB", "unknown")),
            (*FACTS, ("room-assignment", "U404", "", "UC")),
            (*FACTS, ("room-assignment", "1INVALID", "", "UC")),
            (*FACTS, ("net-group", "extra", "MISSING", "", "")),
            (*FACTS, ("net-group", "extra", "", "MISSING", "")),
            (*FACTS, ("net-group", "extra", "", "", "SIGNAL")),
        )
        for facts in variants:
            with self.subTest(added=facts[-1]):
                with self.assertRaises(ProtocolError):
                    decode_policy(policy_receipt(facts), REFS)

    def test_duplicate_declarations_memberships_and_assignment_keys_are_rejected(self):
        for extra in (
            ("room", "1_QP", "different", "0", "0", "1", "1"),
            ("net-group", "DB", "", "", ""),
            ("policy-net", DB_NETS[0]),
            ("net-group-member", "DB", DB_NETS[0]),
            ("room-assignment", "U1", "", "UC"),
            ("room-assignment", "U1", "FUNC_UC", "UC"),
            ("room-assignment", "U1", "", "OTHER"),
        ):
            with self.subTest(extra=extra):
                with self.assertRaises(ProtocolError):
                    decode_policy(policy_receipt((*FACTS, extra)), REFS)

    def test_complete_empty_fact_inventory_is_not_legacy(self):
        facts = tuple(("constraint-set", domain, "DEFAULT") for domain in ("physical", "spacing", "sameNet"))
        result = decode_policy(policy_receipt(facts), set())
        expected = empty_policy()
        expected["digest"] = canonical_digest({"native_policy": "".join(CHUNKS)})
        self.assertEqual(result, expected)

    def test_wire_fact_fields_cannot_bypass_validation(self):
        for extra in (
            ("room", "extra", "1", "0", "0", "0", "1"),
            ("room", "extra", "1", "NaN", "0", "1", "1"),
            ("room", "extra", "", "0", "0", "1", "1"),
            ("room", "x" * 257, "1", "0", "0", "1", "1"),
            ("room-assignment", "U1", "x" * 257, "UC"),
            ("room-assignment", "U1", "extra", ""),
            ("net-group", "", "", "", ""),
            ("constraint-set", "physical", "x" * 257),
            ("policy-net", ""),
            ("policy-net", "x" * 257),
            ("policy-net", None),
        ):
            with self.subTest(extra=extra):
                with self.assertRaises(ProtocolError):
                    decode_policy(policy_receipt((*FACTS, extra)), REFS)

    def test_malformed_synthetic_rows_raise_protocol_error_not_index_error(self):
        original = policy_receipt().records
        for row in original:
            for malformed in (row[:-1], (*row, "extra"), (row[0],)):
                with self.subTest(tag=row[0], length=len(malformed)):
                    with self.assertRaises(ProtocolError):
                        decode_policy(receipt((*original, malformed)), REFS)
        for malformed in ((), None, "policy", 123, (None,), (["policy"],), ("room",) * 17,
                          ("policy-unknown", "opaque"), ("net-group-unknown", "opaque")):
            with self.subTest(malformed=malformed):
                with self.assertRaises(ProtocolError):
                    decode_policy(receipt((malformed,)), REFS)
        for malformed in (None, 42, {}, "records"):
            with self.subTest(records=malformed):
                with self.assertRaises(ProtocolError):
                    decode_policy(Receipt("1" * 32, "2" * 32, "snapshot", "", malformed), REFS)
        for column in range(1, 8):
            for value in (None, True, 1, [], {}):
                header = list(original[1])
                header[column] = value
                with self.subTest(column=column, value=value):
                    with self.assertRaises(ProtocolError):
                        decode_policy(receipt((original[0], tuple(header), *original[2:])), REFS)


class ValidatePolicyTests(unittest.TestCase):
    def test_normalization_is_idempotent_and_returns_independent_containers(self):
        original = decode_policy(policy_receipt(), REFS)
        for key in ("rooms", "room_assignments", "net_groups", "nets"):
            original[key].reverse()
        for names in original["constraint_sets"].values():
            names.reverse()
        for item in original["net_groups"]:
            item["nets"].reverse()
        original["rooms"][2]["bounds"][0] = "-120.0000"
        saved = deepcopy(original)
        result = validate_policy(original, REFS)
        self.assertEqual(original, saved)
        self.assertEqual(result, validate_policy(result, REFS))
        self.assertEqual(result, decode_policy(policy_receipt(), REFS))
        result["rooms"][0]["bounds"][0] = "changed"
        result["room_assignments"][0]["label"] = "changed"
        result["net_groups"][0]["nets"].append("changed")
        result["constraint_sets"]["physical"].append("changed")
        result["nets"].append("changed")
        self.assertEqual(original, saved)

    def test_digest_is_format_only_and_opaque_fields_are_not_accepted(self):
        policy = empty_policy()
        policy["digest"] = "b" * 64
        self.assertEqual(validate_policy(policy, set())["digest"], "b" * 64)
        for digest in ("B" * 64, "a" * 63, "a" * 65, "g" * 64, "", None, 1, [], "a" * 64 + "\n"):
            with self.subTest(digest=digest):
                policy["digest"] = digest
                with self.assertRaises(ProtocolError):
                    validate_policy(policy, set())
        policy = empty_policy()
        policy["native_policy"] = "OPA-BOARD-1;not evaluated;"
        with self.assertRaises(ProtocolError):
            validate_policy(policy, set())

    def test_top_level_and_nested_schemas_are_closed_and_typed(self):
        for value in (None, [], (), "policy", 1, True, {}):
            with self.subTest(value=value):
                with self.assertRaises(ProtocolError):
                    validate_policy(value, REFS)
        original = decode_policy(policy_receipt(), REFS)
        for key in original:
            value = deepcopy(original)
            del value[key]
            with self.subTest(missing=key):
                with self.assertRaises(ProtocolError):
                    validate_policy(value, REFS)
        for target in ("rooms", "room_assignments", "net_groups", "constraint_sets"):
            for operation in ("missing", "extra", "not_object"):
                value = deepcopy(original)
                item = value[target] if target == "constraint_sets" else value[target][0]
                if operation == "missing":
                    del item[next(iter(item))]
                elif operation == "extra":
                    item["unsupported"] = "value"
                elif target == "constraint_sets":
                    value[target] = []
                else:
                    value[target][0] = []
                with self.subTest(target=target, operation=operation):
                    with self.assertRaises(ProtocolError):
                        validate_policy(value, REFS)
        for model in (None, [], "managed-board-v1", "grouped-constraints-v2"):
            value = empty_policy()
            value["model"] = model
            with self.assertRaises(ProtocolError):
                validate_policy(value, REFS)
        for refs in (None, [], {"bad-ref"}, {"1U"}, {1}, {"U" * 32}):
            with self.assertRaises(ProtocolError):
                validate_policy(empty_policy(), refs)

    def test_fact_lists_and_nested_name_lists_require_lists(self):
        original = decode_policy(policy_receipt(), REFS)
        for key in ("rooms", "room_assignments", "net_groups", "nets"):
            for malformed in (None, {}, (), "values"):
                value = deepcopy(original)
                value[key] = malformed
                with self.subTest(key=key, malformed=malformed):
                    with self.assertRaises(ProtocolError):
                        validate_policy(value, REFS)
        for malformed in (None, {}, (), "DEFAULT"):
            for location in ("constraint_sets", "net_groups"):
                value = deepcopy(original)
                if location == "constraint_sets":
                    value[location]["physical"] = malformed
                else:
                    value[location][0]["nets"] = malformed
                with self.assertRaises(ProtocolError):
                    validate_policy(value, REFS)

    def test_names_and_labels_are_bounded_printable_ascii_without_coercion(self):
        locations = (
            ("rooms", "name"), ("rooms", "label"),
            ("room_assignments", "owner"), ("room_assignments", "label"),
            ("net_groups", "name"), ("net_groups", "physical"),
            ("net_groups", "spacing"), ("net_groups", "same_net"),
            ("constraint_sets", "physical"), ("nets", None), ("net_groups", "nets"),
        )
        original = decode_policy(policy_receipt(), REFS)
        for target, key in locations:
            for malformed in ("x" * 257, "\u6587", "line\nbreak", "\x1f", "\x7f", 1, None, [], {}):
                value = deepcopy(original)
                if target == "constraint_sets":
                    value[target][key].append(malformed)
                elif target == "nets":
                    value[target].append(malformed)
                elif key == "nets":
                    value[target][0][key].append(malformed)
                else:
                    value[target][0][key] = malformed
                with self.subTest(target=target, key=key, malformed=malformed):
                    with self.assertRaises(ProtocolError):
                        validate_policy(value, REFS)
        for target, key in locations:
            if key in ("owner", "physical", "spacing", "same_net") and target != "constraint_sets":
                continue
            value = deepcopy(original)
            if target == "constraint_sets":
                value[target][key].append("")
            elif target == "nets":
                value[target].append("")
            elif key == "nets":
                value[target][0][key].append("")
            else:
                value[target][0][key] = ""
            with self.subTest(target=target, key=key, empty=True):
                with self.assertRaises(ProtocolError):
                    validate_policy(value, REFS)

    def test_maximum_length_names_preserve_spaces_punctuation_and_case(self):
        text = ' "Name, MixedCase;()[] ' + "x" * (256 - len(' "Name, MixedCase;()[] '))
        policy = empty_policy()
        policy["rooms"] = [room(text, text)]
        policy["room_assignments"] = [{"refdes": "U1", "owner": text, "label": text}]
        policy["nets"] = [text]
        policy["net_groups"] = [group(text, [text])]
        for domain, key in (("physical", "physical"), ("spacing", "spacing"), ("sameNet", "same_net")):
            policy["constraint_sets"][domain].append(text)
            policy["net_groups"][0][key] = text
        result = validate_policy(policy, REFS)
        self.assertEqual(result["rooms"][0]["name"], text)
        self.assertEqual(result["rooms"][0]["label"], text)
        self.assertEqual(result["room_assignments"][0]["owner"], text)
        self.assertEqual(result["net_groups"][0]["nets"], [text])

    def test_room_rectangles_require_finite_plain_decimal_positive_area(self):
        policy = empty_policy()
        policy["rooms"] = [room()]
        for bounds in (
            None, (), ["0"] * 3, ["0"] * 5, ["0", "0", "0", "1"],
            ["0", "0", "1", "0"], ["1", "0", "0", "1"], ["0", "1", "1", "0"],
        ):
            policy["rooms"][0]["bounds"] = bounds
            with self.subTest(bounds=bounds):
                with self.assertRaises(ProtocolError):
                    validate_policy(policy, set())
        for column in range(4):
            for malformed in ("NaN", "inf", "-inf", "1e2", "01", "+1", ".1", "1.", "1\n",
                              "1000000000", "0.0000000001", None, 0, True, [], {}):
                bounds = ["-1", "-1", "1", "1"]
                bounds[column] = malformed
                policy["rooms"][0]["bounds"] = bounds
                with self.subTest(column=column, malformed=malformed):
                    with self.assertRaises(ProtocolError):
                        validate_policy(policy, set())
        policy["rooms"][0]["bounds"] = ["-0.0000", "-999999999.999999999", "0.000000001", "1.0000"]
        self.assertEqual(validate_policy(policy, set())["rooms"][0]["bounds"],
                         ["0", "-999999999.999999999", "0.000000001", "1"])

    def test_duplicate_labels_and_multiple_function_associations_remain_facts(self):
        policy = empty_policy()
        policy["rooms"] = [room("B"), room("A")]
        policy["room_assignments"] = [
            {"refdes": "U1", "owner": "FUNC_B", "label": "DIFFERENT"},
            {"refdes": "U1", "owner": "FUNC_A", "label": "UNMATCHED"},
            {"refdes": "U1", "owner": "", "label": "UNMATCHED"},
        ]
        policy["nets"] = ["N"]
        policy["net_groups"] = [group("B", ["N"]), group("A", ["N"])]
        result = validate_policy(policy, REFS)
        self.assertEqual([item["label"] for item in result["rooms"]], ["1", "1"])
        self.assertEqual([item["owner"] for item in result["room_assignments"]], ["", "FUNC_A", "FUNC_B"])
        self.assertEqual([item["nets"] for item in result["net_groups"]], [["N"], ["N"]])

    def test_normalized_duplicate_facts_are_rejected(self):
        original = decode_policy(policy_receipt(), REFS)
        for target in ("rooms", "room_assignments", "net_groups", "nets"):
            policy = deepcopy(original)
            policy[target].append(deepcopy(policy[target][0]))
            with self.subTest(target=target):
                with self.assertRaises(ProtocolError):
                    validate_policy(policy, REFS)
        for target in ("constraint_sets", "net_groups"):
            policy = deepcopy(original)
            if target == "constraint_sets":
                policy[target]["sameNet"].append("DEFAULT")
            else:
                policy[target][0]["nets"].append(policy[target][0]["nets"][0])
            with self.assertRaises(ProtocolError):
                validate_policy(policy, REFS)

    def test_normalized_missing_catalogs_and_unknown_references_are_rejected(self):
        original = decode_policy(policy_receipt(), REFS)
        for domain in ("physical", "spacing", "sameNet"):
            policy = deepcopy(original)
            policy["constraint_sets"][domain].remove("DEFAULT")
            with self.assertRaises(ProtocolError):
                validate_policy(policy, REFS)
        for key in ("physical", "spacing", "same_net"):
            policy = deepcopy(original)
            policy["net_groups"][0][key] = "UNKNOWN"
            with self.assertRaises(ProtocolError):
                validate_policy(policy, REFS)
        policy = deepcopy(original)
        policy["net_groups"][0]["nets"].append("UNKNOWN")
        with self.assertRaises(ProtocolError):
            validate_policy(policy, REFS)
        for refdes in ("U404", "1INVALID", "BAD-REF", "U" * 32, None, [], 1):
            policy = deepcopy(original)
            policy["room_assignments"][0]["refdes"] = refdes
            with self.assertRaises(ProtocolError):
                validate_policy(policy, REFS)

    def test_collection_limits_accept_maximum_and_reject_next(self):
        for key, maximum, make in (
            ("rooms", 128, lambda index: room(f"R{index}")),
            ("room_assignments", 8192,
             lambda index: {"refdes": "U1", "owner": f"F{index}", "label": "UNMATCHED"}),
            ("net_groups", 128, lambda index: group(f"G{index}")),
            ("nets", 4096, lambda index: f"N{index}"),
        ):
            policy = empty_policy()
            policy[key] = [make(index) for index in range(maximum)]
            with self.subTest(key=key, boundary="at"):
                self.assertEqual(len(validate_policy(policy, REFS)[key]), maximum)
            policy[key].append(make(maximum))
            with self.subTest(key=key, boundary="above"):
                with self.assertRaises(ProtocolError):
                    validate_policy(policy, REFS)
        for domain in ("physical", "spacing", "sameNet"):
            policy = empty_policy()
            policy["constraint_sets"][domain].extend(f"C{index}" for index in range(31))
            self.assertEqual(len(validate_policy(policy, REFS)["constraint_sets"][domain]), 32)
            policy["constraint_sets"][domain].append("EXTRA")
            with self.assertRaises(ProtocolError):
                validate_policy(policy, REFS)
        policy = empty_policy()
        policy["nets"] = [f"N{index}" for index in range(4096)]
        policy["net_groups"] = [group(nets=policy["nets"])]
        self.assertEqual(len(validate_policy(policy, REFS)["net_groups"][0]["nets"]), 4096)
        policy["net_groups"].append(group("SECOND", policy["nets"][:1]))
        with self.assertRaises(ProtocolError):
            validate_policy(policy, REFS)
        policy["net_groups"][0]["nets"].append("EXTRA")
        with self.assertRaises(ProtocolError):
            validate_policy(policy, REFS)


if __name__ == "__main__":
    unittest.main()
