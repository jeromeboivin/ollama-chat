"""Tests for DocumentIndexer extraction behavior."""

import copy
from unittest.mock import MagicMock, patch

from ollama_chat_lib.document_indexer import DocumentIndexer


class FakeCollection:
    """Small stateful subset of the Chroma collection API used by the indexer."""

    name = "test_docs"

    def __init__(self):
        self.records = {}
        self.get_calls = 0
        self.delete_calls = []

    def get(self, ids=None, where=None, include=None, limit=None):
        self.get_calls += 1
        selected = []
        for record_id, record in self.records.items():
            if ids is not None and record_id not in ids:
                continue
            if where is not None and any(record["metadata"].get(key) != value for key, value in where.items()):
                continue
            selected.append((record_id, record))
            if limit and len(selected) >= limit:
                break
        return {
            "ids": [record_id for record_id, _ in selected],
            "metadatas": [record["metadata"] for _, record in selected],
            "documents": [record["document"] for _, record in selected],
        }

    def upsert(self, documents, metadatas, ids, embeddings=None):
        for index, record_id in enumerate(ids):
            self.records[record_id] = {
                "document": documents[index],
                "metadata": copy.deepcopy(metadatas[index]),
                "embedding": embeddings[index] if embeddings else None,
            }

    def delete(self, ids=None, where=None):
        deleted_ids = []
        if ids is not None:
            for record_id in ids:
                if record_id in self.records:
                    deleted_ids.append(record_id)
                    del self.records[record_id]
        elif where is not None:
            for record_id, record in list(self.records.items()):
                if all(record["metadata"].get(key) == value for key, value in where.items()):
                    deleted_ids.append(record_id)
                    del self.records[record_id]
        self.delete_calls.append(deleted_ids)


def make_indexer(root_folder, collection):
    client = MagicMock()
    client.get_or_create_collection.return_value = collection
    return DocumentIndexer(
        root_folder=str(root_folder),
        collection_name="test_docs",
        chroma_client=client,
        embeddings_model=None,
        verbose=False,
    )


def write_duplicate_files(root_folder):
    first = root_folder / "first" / "RD00007608.txt"
    second = root_folder / "second" / "RD00007608.txt"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    first.write_text("first record", encoding="utf-8")
    second.write_text("second record", encoding="utf-8")
    return first, second


class TestDocumentIndexer:

    def test_collision_safe_ids_index_duplicate_filenames_and_rerun_cleanly(self, tmp_path):
        first, second = write_duplicate_files(tmp_path)
        collection = FakeCollection()
        indexer = make_indexer(tmp_path, collection)

        options = {
            "allow_chunks": False,
            "no_chunking_confirmation": True,
            "add_summary": False,
            "document_id_strategy": "collision-safe",
            "document_id_namespace": "rd-cases-2026",
        }
        indexer.index_documents(**options)

        assert len(collection.records) == 2
        assert collection.get_calls == 1
        assert "RD00007608" in collection.records
        collision_ids = [record_id for record_id in collection.records if record_id != "RD00007608"]
        assert len(collision_ids) == 1
        assert collision_ids[0].startswith("RD00007608__")
        assert len(collision_ids[0]) <= 63

        metadatas = [record["metadata"] for record in collection.records.values()]
        assert {metadata["title"] for metadata in metadatas} == {"RD00007608"}
        assert {metadata["filePath"] for metadata in metadatas} == {str(first), str(second)}
        assert {metadata["documentRelativePath"] for metadata in metadatas} == {
            "first/RD00007608.txt",
            "second/RD00007608.txt",
        }
        assert {metadata["documentNamespace"] for metadata in metadatas} == {"rd-cases-2026"}

        original_records = copy.deepcopy(collection.records)
        indexer.index_documents(**options)
        assert collection.records == original_records

    def test_collision_safe_ids_preserve_matching_legacy_record(self, tmp_path):
        first, second = write_duplicate_files(tmp_path)
        collection = FakeCollection()
        collection.records["RD00007608"] = {
            "document": "legacy content that must not change",
            "metadata": {"id": "RD00007608", "filePath": str(first), "legacy": True},
            "embedding": [9.9],
        }
        legacy_record = copy.deepcopy(collection.records["RD00007608"])

        make_indexer(tmp_path, collection).index_documents(
            allow_chunks=False,
            no_chunking_confirmation=True,
            add_summary=False,
            document_id_strategy="collision-safe",
            document_id_namespace="rd-cases-2026",
        )

        assert collection.records["RD00007608"] == legacy_record
        assert len(collection.records) == 2
        new_record = next(record for key, record in collection.records.items() if key != "RD00007608")
        assert new_record["document"] == "second record"
        assert new_record["metadata"]["filePath"] == str(second)

    def test_collision_safe_ids_are_stable_when_dataset_root_moves(self, tmp_path):
        first_root = tmp_path / "original"
        moved_root = tmp_path / "moved"
        write_duplicate_files(first_root)
        write_duplicate_files(moved_root)
        collection = FakeCollection()
        options = {
            "allow_chunks": False,
            "no_chunking_confirmation": True,
            "add_summary": False,
            "document_id_strategy": "collision-safe",
            "document_id_namespace": "stable-dataset",
        }

        make_indexer(first_root, collection).index_documents(**options)
        original_records = copy.deepcopy(collection.records)
        make_indexer(moved_root, collection).index_documents(**options)

        assert collection.records == original_records

    def test_collision_safe_ids_separate_dataset_namespaces(self, tmp_path):
        write_duplicate_files(tmp_path)
        collection = FakeCollection()
        indexer = make_indexer(tmp_path, collection)
        base_options = {
            "allow_chunks": False,
            "no_chunking_confirmation": True,
            "add_summary": False,
            "document_id_strategy": "collision-safe",
        }

        indexer.index_documents(document_id_namespace="dataset-a", **base_options)
        indexer.index_documents(document_id_namespace="dataset-b", **base_options)

        assert len(collection.records) == 4
        assert {record["metadata"]["documentNamespace"] for record in collection.records.values()} == {
            "dataset-a",
            "dataset-b",
        }

    def test_collision_safe_ids_reject_missing_namespace_before_indexing(self, tmp_path):
        collection = FakeCollection()
        indexer = make_indexer(tmp_path, collection)

        try:
            indexer.index_documents(
                allow_chunks=False,
                no_chunking_confirmation=True,
                document_id_strategy="collision-safe",
            )
        except ValueError as error:
            assert "document_id_namespace" in str(error)
        else:
            raise AssertionError("Expected collision-safe indexing to require a namespace")
        assert collection.records == {}

    def test_collision_safe_ids_refuse_to_overwrite_fallback_owner(self, tmp_path):
        first, second = write_duplicate_files(tmp_path)
        collection = FakeCollection()
        indexer = make_indexer(tmp_path, collection)
        first_identity = indexer._build_source_identity(str(first), "dataset")
        second_identity = indexer._build_source_identity(str(second), "dataset")
        fallback_id = indexer._generate_collision_id("RD00007608", second_identity)
        collection.records["RD00007608"] = {
            "document": "first",
            "metadata": {"id": "RD00007608", **first_identity, "filePath": str(first)},
            "embedding": None,
        }
        collection.records[fallback_id] = {
            "document": "unexpected owner",
            "metadata": {"id": fallback_id, **first_identity, "filePath": str(first)},
            "embedding": None,
        }

        try:
            indexer._resolve_document_id(str(second), strategy="collision-safe", namespace="dataset")
        except ValueError as error:
            assert fallback_id in str(error)
        else:
            raise AssertionError("Expected an occupied fallback ID to be rejected")

    def test_collision_safe_ids_use_distinct_chunk_parents(self, tmp_path):
        write_duplicate_files(tmp_path)
        collection = FakeCollection()

        make_indexer(tmp_path, collection).index_documents(
            allow_chunks=True,
            no_chunking_confirmation=True,
            add_summary=False,
            store_full_docs=False,
            document_id_strategy="collision-safe",
            document_id_namespace="chunked-dataset",
        )

        assert len(collection.records) == 2
        assert "RD00007608_0" in collection.records
        other_id = next(record_id for record_id in collection.records if record_id != "RD00007608_0")
        assert other_id.startswith("RD00007608__") and other_id.endswith("_0")
        assert len({record["metadata"]["id"] for record in collection.records.values()}) == 2

    def test_collision_id_respects_maximum_length(self, tmp_path):
        collection = FakeCollection()
        indexer = make_indexer(tmp_path, collection)
        identity = {
            "documentSourceKey": "a" * 64,
        }
        collision_id = indexer._generate_collision_id("x" * 200, identity)
        assert len(collision_id) == 63
        assert collision_id.endswith("__" + "a" * 16)

    def test_reindex_document_replaces_chunked_records_and_cleans_cache(self, tmp_path):
        file_path = tmp_path / "doc.txt"
        file_path.write_text("A" * 1500, encoding="utf-8")
        collection = FakeCollection()
        indexer = make_indexer(tmp_path, collection)

        indexer.index_documents(
            allow_chunks=True,
            no_chunking_confirmation=True,
            add_summary=False,
            store_full_docs=False,
        )

        assert set(collection.records) == {"doc_0", "doc_1"}

        file_path.write_text("updated content", encoding="utf-8")
        result = indexer.reindex_document(
            str(file_path),
            allow_chunks=False,
            no_chunking_confirmation=True,
            add_summary=False,
        )

        assert result["action"] == "updated"
        assert result["deleted"] == 2
        assert result["status"] == "indexed"
        assert set(collection.records) == {"doc_0"}
        assert collection.records["doc_0"]["metadata"]["id"] == "doc"
        assert collection.records["doc_0"]["metadata"]["addSummary"] is False
        assert collection.records["doc_0"]["metadata"]["store_full_docs"] is False
        assert indexer._document_id_exists("doc_1") is False

    def test_reindex_document_preserves_existing_collision_safe_identity(self, tmp_path):
        first, second = write_duplicate_files(tmp_path)
        collection = FakeCollection()
        indexer = make_indexer(tmp_path, collection)

        indexer.index_documents(
            allow_chunks=False,
            no_chunking_confirmation=True,
            add_summary=False,
            document_id_strategy="collision-safe",
            document_id_namespace="rd-cases-2026",
        )

        original_id = next(
            record_id
            for record_id, record in collection.records.items()
            if record["metadata"]["filePath"] == str(second)
        )
        second.write_text("second record updated", encoding="utf-8")

        result = indexer.reindex_document(
            str(second),
            allow_chunks=False,
            no_chunking_confirmation=True,
            add_summary=False,
            document_id_strategy="legacy",
        )

        assert result["action"] == "updated"
        assert result["documentId"] == collection.records[original_id]["metadata"]["id"]
        assert original_id in collection.records
        assert collection.records[original_id]["document"] == "second record updated"
        assert collection.records[original_id]["metadata"]["documentIdStrategy"] == "collision-safe"
        assert collection.records[original_id]["metadata"]["documentNamespace"] == "rd-cases-2026"

    def test_reindex_document_adds_missing_file(self, tmp_path):
        file_path = tmp_path / "new_doc.txt"
        file_path.write_text("brand new", encoding="utf-8")
        collection = FakeCollection()

        result = make_indexer(tmp_path, collection).reindex_document(
            str(file_path),
            allow_chunks=False,
            no_chunking_confirmation=True,
            add_summary=False,
        )

        assert result["action"] == "added"
        assert result["deleted"] == 0
        assert result["status"] == "indexed"
        assert set(collection.records) == {"new_doc"}

    def test_reindex_path_updates_only_target_subtree_and_adds_new_files(self, tmp_path):
        subtree = tmp_path / "subset"
        other = tmp_path / "other"
        subtree.mkdir()
        other.mkdir()
        existing_in_subtree = subtree / "inside.txt"
        untouched_outside = other / "outside.txt"
        existing_in_subtree.write_text("inside original", encoding="utf-8")
        untouched_outside.write_text("outside original", encoding="utf-8")

        collection = FakeCollection()
        indexer = make_indexer(tmp_path, collection)
        indexer.index_documents(
            allow_chunks=False,
            no_chunking_confirmation=True,
            add_summary=False,
        )

        existing_in_subtree.write_text("inside updated", encoding="utf-8")
        new_in_subtree = subtree / "new_inside.txt"
        new_in_subtree.write_text("new file", encoding="utf-8")

        result = indexer.reindex_path(
            str(subtree),
            allow_chunks=False,
            no_chunking_confirmation=True,
            add_summary=False,
        )

        assert result["processed"] == 2
        assert result["updated"] == 1
        assert result["added"] == 1
        assert result["errors"] == 0
        assert collection.records["inside"]["document"] == "inside updated"
        assert collection.records["outside"]["document"] == "outside original"
        assert collection.records["new_inside"]["document"] == "new file"

    def test_index_documents_uses_end_of_document_when_end_marker_is_blank(self, tmp_path):
        file_path = tmp_path / "doc.txt"
        content = "before [START] after to end"
        file_path.write_text(content, encoding="utf-8")

        client = MagicMock()
        collection = MagicMock()
        collection.get.return_value = {"ids": []}
        client.get_or_create_collection.return_value = collection

        indexer = DocumentIndexer(
            root_folder=str(tmp_path),
            collection_name="test_docs",
            chroma_client=client,
            embeddings_model="test-embed",
            verbose=False,
        )

        with patch("ollama_chat_lib.document_indexer.on_user_input", side_effect=["y", "[START]", ""]), \
             patch("ollama_chat_lib.document_indexer.on_print"), \
             patch("ollama_chat_lib.document_indexer.ollama.embeddings", return_value={"embedding": [0.1, 0.2]}) as mock_embeddings:
            indexer.index_documents(allow_chunks=False, no_chunking_confirmation=False, add_summary=False)

        assert mock_embeddings.call_count == 1
        assert mock_embeddings.call_args.kwargs["prompt"] == " after to end"

        collection.upsert.assert_called_once()
        metadata = collection.upsert.call_args.kwargs["metadatas"][0]
        assert metadata["extraction_used"] is True
        assert metadata["extract_start"] == "[START]"
        assert "extract_end" not in metadata
        assert metadata["extracted_length"] == len(" after to end")
        assert metadata["original_length"] == len(content)

    def test_index_documents_offers_long_document_extraction_before_truncating(self, tmp_path):
        marker = "## Main Code"
        extracted_tail = "\nrelevant implementation details\n" * 20
        content = ("x" * 9000) + marker + extracted_tail
        file_path = tmp_path / "doc.txt"
        file_path.write_text(content, encoding="utf-8")

        client = MagicMock()
        collection = MagicMock()
        collection.get.return_value = {"ids": []}
        client.get_or_create_collection.return_value = collection

        indexer = DocumentIndexer(
            root_folder=str(tmp_path),
            collection_name="test_docs",
            chroma_client=client,
            embeddings_model="test-embed",
            verbose=False,
        )

        with patch("ollama_chat_lib.document_indexer.on_user_input", side_effect=["n", "y", marker, ""]), \
             patch("ollama_chat_lib.document_indexer.on_print"), \
             patch("ollama_chat_lib.document_indexer.ollama.embeddings", return_value={"embedding": [0.1, 0.2]}) as mock_embeddings:
            indexer.index_documents(allow_chunks=False, no_chunking_confirmation=False, add_summary=False)

        assert mock_embeddings.call_count == 1
        assert mock_embeddings.call_args.kwargs["prompt"] == extracted_tail

        collection.upsert.assert_called_once()
        metadata = collection.upsert.call_args.kwargs["metadatas"][0]
        assert metadata["extraction_used"] is True
        assert metadata["extract_start"] == marker
        assert "extract_end" not in metadata
        assert metadata["extracted_length"] == len(extracted_tail)
        assert metadata["original_length"] == len(content)

    def test_index_documents_retries_with_smaller_prompt_after_truncation_failure(self, tmp_path):
        content = "x" * 9000
        file_path = tmp_path / "doc.txt"
        file_path.write_text(content, encoding="utf-8")

        client = MagicMock()
        collection = MagicMock()
        collection.get.return_value = {"ids": []}
        client.get_or_create_collection.return_value = collection

        indexer = DocumentIndexer(
            root_folder=str(tmp_path),
            collection_name="test_docs",
            chroma_client=client,
            embeddings_model="test-embed",
            verbose=False,
        )

        prompt_lengths = []

        def fake_embeddings(*, prompt, model, options):
            prompt_lengths.append(len(prompt))
            if len(prompt_lengths) == 1:
                raise RuntimeError("input too long for embedding context")
            return {"embedding": [0.1, 0.2]}

        with patch("ollama_chat_lib.document_indexer.on_user_input", side_effect=["n", "n"]), \
             patch("ollama_chat_lib.document_indexer.on_print"), \
             patch("ollama_chat_lib.document_indexer.ollama.embeddings", side_effect=fake_embeddings):
            indexer.index_documents(allow_chunks=False, no_chunking_confirmation=False, add_summary=False)

        assert prompt_lengths == [8192, 4096]
        collection.upsert.assert_called_once()