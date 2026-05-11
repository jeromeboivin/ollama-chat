"""Tests for DocumentIndexer extraction behavior."""

from unittest.mock import MagicMock, patch

from ollama_chat_lib.document_indexer import DocumentIndexer


class TestDocumentIndexer:

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