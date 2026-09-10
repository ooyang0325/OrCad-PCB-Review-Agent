import contextlib
from copy import deepcopy
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from orcad_placement_agent import expertise, references
from orcad_placement_agent.advisory import build_context
from orcad_placement_agent.agent_tools import AgentActions, AgentActionError
from orcad_placement_agent.cli import main
from orcad_placement_agent.knowledge import ExtractedDocument, KnowledgeError, index_books


class BundledExpertiseTests(unittest.TestCase):
    def test_all_original_packs_are_complete_and_independently_cited(self):
        catalog = expertise.catalog()
        self.assertEqual(catalog["card_count"], 36)
        self.assertEqual(len(catalog["packs"]), 3)
        for pack in catalog["packs"]:
            self.assertEqual(pack["card_count"], 12)
            self.assertGreaterEqual(len(pack["sources"]), 3)
            for entry in pack["cards"]:
                rule = expertise.rule(entry["id"])
                self.assertEqual(rule["source_kind"], "bundled_synthesis")
                self.assertNotIn("pdf_page", rule)
                self.assertIn(entry["id"], rule["citation"])
                self.assertTrue(rule["required_inputs"])
                self.assertGreaterEqual(len(rule["checks"]), 3)
                self.assertTrue(rule["limits"])
                self.assertTrue(rule["sources"])

    def test_search_covers_key_domains_without_pdf_or_native_access(self):
        queries = {
            "decoupling mounting inductance": "power-thermal",
            "switching converter loop": "power-thermal",
            "thermal placement heat": "power-thermal",
            "return paths reference plane": "signal-routing",
            "BGA fanout escape": "signal-routing",
            "test probe access": "placement-manufacturing",
            "isolation creepage clearance": "placement-manufacturing",
        }
        with (
            patch("orcad_placement_agent.knowledge.search", side_effect=AssertionError("No PDF access")),
            patch("orcad_placement_agent.knowledge.catalog", side_effect=AssertionError("No PDF access")),
        ):
            for query, pack in queries.items():
                with self.subTest(query=query):
                    result = references.search(query)
                    self.assertTrue(result["hits"])
                    self.assertIn(pack, {hit["pack_id"] for hit in result["hits"]})
                    self.assertEqual(result["supplement_status"], "not_configured")
                    self.assertEqual(result, references.search(query))
                    for hit in result["hits"]:
                        self.assertLessEqual(len(hit["excerpt"]), 450)
                        self.assertTrue(expertise.rule(hit["card_id"])["checks"])

    def test_bounds_unknown_rules_and_topics_fail_explicitly(self):
        for query in ("", " ", "x" * 501, "the and to"):
            with self.assertRaises(KnowledgeError):
                expertise.search(query)
        for limit in (True, 0, 21, "5"):
            with self.assertRaises(KnowledgeError):
                expertise.search("placement", limit=limit)
        for card_id in ("../file", "unknown-rule", ""):
            with self.assertRaises(KnowledgeError):
                expertise.rule(card_id)
        with self.assertRaises(KnowledgeError):
            expertise.search("placement", topic="autoplace")
        self.assertEqual(expertise.search("zzzznotaword")["hits"], [])
        self.assertEqual(expertise.search("\u53bb\u8026")["hits"], [])

    def test_package_schema_rejects_broken_provenance_and_missing_cautions(self):
        original = expertise._packs()[0]
        for mutation in (
            lambda pack: pack.update(schema_version=True),
            lambda pack: pack["cards"][0].update(limits=[]),
            lambda pack: pack["cards"][0]["references"][0].update(source_id="unknown"),
            lambda pack: pack["cards"][0]["references"][0].update(pdf_pages=[0]),
            lambda pack: pack["cards"][0]["references"][0].update(pdf_pages=[True]),
            lambda pack: pack["cards"][0].update(topics=["unknown"]),
            lambda pack: pack["cards"].append(pack["cards"][0]),
            lambda pack: pack["sources"][0].update(local_filename="../private.pdf"),
        ):
            changed = deepcopy(original)
            mutation(changed)
            with self.assertRaises(KnowledgeError):
                expertise.validate_pack(changed, original["pack_id"])

    def test_results_cannot_mutate_the_cached_knowledge(self):
        catalog = expertise.catalog()
        card_id = catalog["packs"][0]["cards"][0]["id"]
        catalog["packs"][0]["cards"].clear()
        rule = expertise.rule(card_id)
        rule["checks"].clear()
        self.assertTrue(expertise.rule(card_id)["checks"])
        self.assertEqual(expertise.catalog()["card_count"], 36)

    def test_app_reference_actions_never_open_a_board_or_accept_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("orcad_placement_agent.agent_tools.Session") as native:
                actions = AgentActions(Path(directory), session_factory=native)
                result = actions.dispatch({"action": "reference-search", "query": "decoupling"})
                card_id = result["data"]["hits"][0]["card_id"]
                self.assertEqual(actions.dispatch({"action": "reference-catalog"})["data"]["card_count"], 36)
                self.assertTrue(actions.dispatch({"action": "reference-rule", "card_id": card_id})["data"]["checks"])
                for request in (
                    {"action": "reference-search", "query": "placement", "database": directory},
                    {"action": "reference-rule", "card_id": "../file"},
                    {"action": "reference-search", "query": 123},
                ):
                    with self.assertRaises(AgentActionError):
                        actions.dispatch(request)
                native.assert_not_called()

    def test_default_cli_and_context_work_without_books_database_or_packet(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch("orcad_placement_agent.knowledge.catalog", side_effect=AssertionError("No index")):
                for command in (["catalog"], ["search", "decoupling"]):
                    output = io.StringIO()
                    with contextlib.redirect_stdout(output):
                        self.assertEqual(main(["knowledge", *command, "--json"]), 0)
                    self.assertTrue(json.loads(output.getvalue()))
                path, context = build_context("Review placement", output_directory=root)
            self.assertTrue(path.is_file())
            self.assertEqual(context["coverage"]["documents"], 0)
            self.assertEqual(context["coverage"]["bundled"]["card_count"], 36)
            self.assertTrue(context["evidence"])
            self.assertTrue(all(entry["guidance"]["limits"] for entry in context["evidence"]))
            self.assertFalse(context["authority"]["approves_board_changes"])
            card_id = context["evidence"][0]["card_id"]
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(main(["knowledge", "rule", card_id, "--json"]), 0)
            self.assertTrue(json.loads(output.getvalue())["checks"])


class OptionalSupplementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.database = self.root / "knowledge.sqlite3"

    def test_missing_or_corrupt_supplement_warns_but_keeps_real_bundled_guidance(self):
        for corrupt in (False, True):
            if corrupt:
                self.database.write_bytes(b"Not SQLite")
            catalog = references.catalog(self.database)
            result = references.search("placement", self.database)
            self.assertEqual(catalog["supplement_status"], "unavailable")
            self.assertEqual(catalog["bundled"]["card_count"], 36)
            self.assertTrue(catalog["warnings"])
            self.assertTrue(result["warnings"])
            self.assertTrue(result["hits"])
            self.assertEqual(result["supplement_hits"], [])
        with self.assertRaises(KnowledgeError):
            references.page("original.pdf", 1)

    def create_reference(self):
        books = self.root / "books"
        books.mkdir()
        source = books / "original.pdf"
        source.write_bytes(b"Original test source")
        index_books(books, self.database, extractor=lambda _path: ExtractedDocument(
            "Original test source", 1, ((1, "Decoupling capacitor placement and loop inductance."),), "indexed",
        ))
        return source

    def test_malformed_optional_notices_cannot_disable_bundled_guidance(self):
        self.create_reference()
        for notices in ("{", "null", "123", '["valid", 123]', '{"unexpected": "object"}'):
            with self.subTest(notices=notices):
                with contextlib.closing(sqlite3.connect(self.database)) as connection, connection:
                    connection.execute("UPDATE documents SET notices=?", (notices,))
                catalog = references.catalog(self.database)
                result = references.search("decoupling", self.database)
                self.assertEqual(catalog["bundled"]["card_count"], 36)
                self.assertEqual(catalog["supplement_status"], "unavailable")
                self.assertTrue(catalog["warnings"])
                self.assertTrue(result["warnings"])
                self.assertTrue(result["hits"])
                _, context = build_context("Review decoupling", self.database,
                                           output_directory=self.root / "contexts")
                self.assertTrue(context["evidence"])
                self.assertTrue(context["warnings"])
                with self.assertRaises(KnowledgeError):
                    references.page("original.pdf", 1, self.database)

    def test_optional_pdf_hits_are_distinct_and_stale_sources_are_not_used(self):
        source = self.create_reference()
        result = references.search("decoupling", self.database)
        self.assertEqual(result["hits"][0]["source_kind"], "bundled_synthesis")
        self.assertEqual(result["supplement_hits"][0]["source_kind"], "local_pdf")
        self.assertEqual(result["supplement_hits"][0]["pdf_page"], 1)
        self.assertEqual(references.page("original.pdf", 1, self.database)["source_kind"], "local_pdf")
        source.write_bytes(b"Changed source, not yet reindexed")
        self.assertEqual(references.catalog(self.database)["supplement_status"], "stale")
        result = references.search("decoupling", self.database)
        self.assertTrue(result["hits"])
        self.assertEqual(result["supplement_hits"], [])
        self.assertTrue(result["warnings"])


if __name__ == "__main__":
    unittest.main()
