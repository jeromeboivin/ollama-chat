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
        assert metadata["extract_end"] is None
        assert metadata["extracted_length"] == len(" after to end")
        assert metadata["original_length"] == len(content)