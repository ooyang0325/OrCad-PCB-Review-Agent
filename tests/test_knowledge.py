import contextlib
import io
import json
import sqlite3
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from orcad_placement_agent.cli import main
from orcad_placement_agent.knowledge import (
    ExtractedDocument, KnowledgeError, catalog, extract_pdf, index_books, page, search,
)


class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.books = self.root / "books"
        self.books.mkdir()
        self.database = self.root / "cache" / "knowledge.sqlite3"
        self.first = self.books / "layout.pdf"
        self.first.write_bytes(b"original fixture content")
        self.calls = []

    def extract(self, path):
        self.calls.append(path.name)
        if path.name == "scanned.pdf":
            return ExtractedDocument(
                "Scanned reference", 2, (), "no_text",
                ("PDF pages contain no extractable text; OCR needed.",),
            )
        return ExtractedDocument("Original test layout reference", 3, (
            (1, "Use short decoupling connections and consider the complete return path."),
            (2, "Keep switching current loops compact. Board geometry alone cannot prove EMI compliance."),
            (3, "\u53bb\u8026\u96fb\u5bb9\u61c9\u63a5\u8fd1\u96fb\u6e90\u8173\uff0c\u56de\u6d41\u8def\u5f91\u4e0d\u53ef\u4e2d\u65b7\u3002"),
        ), "indexed")

    def build(self, **kwargs):
        return index_books(self.books, self.database, extractor=self.extract, **kwargs)

    def test_index_search_and_page_citations(self):
        self.build()
        result = search("decoupling return", self.database)
        self.assertEqual(result["match_mode"], "all_terms")
        self.assertEqual(len(result["hits"]), 1)
        hit = result["hits"][0]
        self.assertEqual(hit["pdf_page"], 1)
        self.assertEqual(hit["citation"], "layout.pdf (PDF page 1)")
        evidence = page(hit["source"], 1, self.database, characters=20)
        self.assertEqual(len(evidence["text"]), 20)
        self.assertTrue(evidence["truncated"])

    def test_no_text_and_missing_pages_are_explicit(self):
        (self.books / "scanned.pdf").write_bytes(b"scanned placeholder")
        self.build()
        documents = catalog(self.database)
        scanned = next(item for item in documents if item["source"] == "scanned.pdf")
        self.assertEqual(scanned["status"], "no_text")
        self.assertTrue(scanned["notices"])
        with self.assertRaises(KnowledgeError):
            page("scanned.pdf", 1, self.database)

    def test_incremental_metadata_and_explicit_rebuild(self):
        self.build()
        second = self.build()
        self.assertEqual((second["updated"], second["unchanged"]), (0, 1))
        self.assertEqual(len(self.calls), 1)
        self.build(rebuild=True)
        self.assertEqual(len(self.calls), 2)

    def test_extractor_revision_change_requires_reindexing(self):
        self.build()
        with contextlib.closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute("DELETE FROM metadata WHERE key='extractor_revision'")
        with self.assertRaises(KnowledgeError):
            search("decoupling", self.database)
        self.assertEqual(self.build()["updated"], 1)
        self.assertTrue(catalog(self.database)[0]["fresh"])

    def test_changed_document_blocks_stale_citations(self):
        self.build()
        self.first.write_bytes(b"new reference file content")
        self.assertFalse(catalog(self.database)[0]["fresh"])
        with self.assertRaisesRegex(KnowledgeError, "changed"):
            search("decoupling", self.database)
        with self.assertRaises(KnowledgeError):
            page("layout.pdf", 1, self.database)
        self.build()
        self.assertTrue(catalog(self.database)[0]["fresh"])

    def test_removed_document_is_pruned_with_fts_entries(self):
        second = self.books / "second.pdf"
        second.write_bytes(b"second reference")
        self.build()
        self.first.unlink()
        result = self.build()
        self.assertEqual(result["removed"], 1)
        self.assertEqual({hit["source"] for hit in search("decoupling", self.database)["hits"]}, {"second.pdf"})

    def test_source_library_cannot_be_silently_retargeted(self):
        self.build()
        other = self.root / "other"
        other.mkdir()
        (other / "another.pdf").write_bytes(b"another book")
        with self.assertRaisesRegex(KnowledgeError, "different library"):
            index_books(other, self.database, extractor=self.extract)

    def test_cjk_substrings_are_searchable(self):
        self.build()
        result = search("\u53bb\u8026", self.database)
        self.assertEqual(result["match_mode"], "substring")
        self.assertEqual(result["hits"][0]["pdf_page"], 3)

    def test_relaxed_search_is_labeled_and_empty_results_are_not_advice(self):
        self.build()
        result = search("decoupling notpresent", self.database)
        self.assertEqual(result["match_mode"], "any_term")
        self.assertTrue(result["hits"])
        self.assertEqual(search("absentword", self.database)["hits"], [])

    def test_search_syntax_and_source_paths_are_not_executed(self):
        self.build()
        self.assertEqual(search('x" OR 1=1 --', self.database)["hits"], [])
        with self.assertRaises(KnowledgeError):
            page("../outside.pdf", 1, self.database)

    def test_invalid_query_limits_and_offsets_are_explicit(self):
        self.build()
        for query, limit in [("", 5), ("x", 0), ("x", 21), ("x" * 501, 5)]:
            with self.assertRaises(KnowledgeError):
                search(query, self.database, limit=limit)
        for number, offset, count in [(0, 0, 10), (1, -1, 10), (1, 0, 4001), (1, 9999, 10)]:
            with self.assertRaises(KnowledgeError):
                page("layout.pdf", number, self.database, offset=offset, characters=count)

    def test_missing_index_and_empty_library_fail_explicitly(self):
        with self.assertRaises(KnowledgeError):
            search("decoupling", self.database)
        self.first.unlink()
        with self.assertRaises(KnowledgeError):
            self.build()

    def test_inconsistent_page_numbers_do_not_publish_document(self):
        def bad(_path):
            return ExtractedDocument("Bad", 1, ((1, "one"), (1, "duplicate")), "indexed")
        with self.assertRaises(KnowledgeError):
            index_books(self.books, self.database, extractor=bad)
        self.assertEqual(catalog(self.database), [])

    def test_source_change_during_extraction_is_detected(self):
        def changing(path):
            data = self.extract(path)
            path.write_bytes(b"changed while extracting")
            return data
        with self.assertRaisesRegex(KnowledgeError, "during extraction"):
            index_books(self.books, self.database, extractor=changing)

    def test_cli_search_never_constructs_a_cadence_session(self):
        self.build()
        output = io.StringIO()
        with patch("orcad_placement_agent.cli.Session") as native, contextlib.redirect_stdout(output):
            result = main([
                "knowledge", "search", "decoupling", "--database", str(self.database), "--json"
            ])
        self.assertEqual(result, 0)
        native.assert_not_called()
        self.assertEqual(json.loads(output.getvalue())["hits"][0]["pdf_page"], 1)


class RealPDFExtractionTests(unittest.TestCase):
    def test_normalized_page_size_is_also_bounded(self):
        try:
            import pypdf
        except ImportError:
            self.skipTest("Optional knowledge extra is not installed.")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "original.pdf"
            path.write_bytes(b"stubbed original PDF")
            reader = Mock(is_encrypted=False, metadata={})
            reader.pages = [Mock(extract_text=Mock(return_value="\ufb03" * 5))]
            with (
                patch("pypdf.PdfReader", return_value=reader),
                patch("orcad_placement_agent.knowledge.MAX_PAGE_CHARACTERS", 10),
            ):
                result = extract_pdf(path)
            self.assertEqual(result.pages, ())
            self.assertEqual(result.status, "no_text")
            self.assertIn("normalized text exceeds", result.notices[0])

    def test_original_pdf_text_and_empty_page_are_extracted(self):
        try:
            from pypdf import PdfWriter
            from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
        except ImportError:
            self.skipTest("Optional knowledge extra is not installed.")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "original.pdf"
            writer = PdfWriter()
            page_object = writer.add_blank_page(200, 200)
            font = DictionaryObject({
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            })
            page_object[NameObject("/Resources")] = DictionaryObject({
                NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})
            })
            stream = DecodedStreamObject()
            stream.set_data(b"BT /F1 12 Tf 20 100 Td (Original test: decoupling and return paths.) Tj ET")
            page_object[NameObject("/Contents")] = writer._add_object(stream)
            writer.add_blank_page(200, 200)
            writer.write(path)
            result = extract_pdf(path)
            self.assertEqual(result.total_pages, 2)
            self.assertEqual(result.status, "partial")
            self.assertIn("decoupling", result.pages[0][1])
            self.assertEqual(result.pages[0][0], 1)
            self.assertIn("page 2", result.notices[0])


if __name__ == "__main__":
    unittest.main()
