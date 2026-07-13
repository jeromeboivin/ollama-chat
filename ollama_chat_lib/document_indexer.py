"""DocumentIndexer: index and search documents with ChromaDB embeddings."""

import hashlib
import os
import re
from datetime import datetime
from urllib.parse import urljoin

import ollama
from colorama import Fore, Style
from PyPDF2 import PdfReader
from tqdm import tqdm

from ollama_chat_lib import state
from ollama_chat_lib.io_hooks import on_print, on_user_input
from ollama_chat_lib.splitters import MarkdownSplitter, TabularDataSplitter
from ollama_chat_lib.terminal_ui import prompt_for_confirmation
from ollama_chat_lib.text_extraction import (
    extract_text_from_csv,
    extract_text_from_docx,
    extract_text_from_html,
    extract_text_from_pptx,
    extract_text_from_xlsx,
    is_html,
    is_markdown,
)


class DocumentIndexer:
    def __init__(self, root_folder, collection_name, chroma_client, embeddings_model, verbose=False, summary_model=None, ask_fn=None):
        self.root_folder = root_folder
        self.collection_name = collection_name
        self.client = chroma_client
        self.model = embeddings_model  # For embeddings only
        self.summary_model = summary_model
        self.collection = self.client.get_or_create_collection(name=self.collection_name)
        self.verbose = verbose
        self._ask_fn = ask_fn
        self._document_identity_cache = None
        self._document_path_cache = None

        if verbose:
            on_print(f"DocumentIndexer initialized with embedding model: {self.model}", Fore.WHITE + Style.DIM)
            if self.summary_model:
                on_print(f"Using summary model: {self.summary_model}", Fore.WHITE + Style.DIM)
            on_print(f"Using collection: {self.collection.name}", Fore.WHITE + Style.DIM)
            on_print(f"Verbose mode is {'on' if self.verbose else 'off'}", Fore.WHITE + Style.DIM)
            on_print(f"Using embeddings model: {self.model}", Fore.WHITE + Style.DIM)

    def _get_max_embedding_chars(self, num_ctx=None):
        """Return the character budget used for embedding prompts."""
        if num_ctx and isinstance(num_ctx, int) and num_ctx > 0:
            max_tokens = num_ctx
        else:
            max_tokens = 2048
        return max_tokens * 4

    def _prepare_text_for_embedding(self, text, num_ctx=None, max_chars=None):
        """
        Prepare text to send to the embedding model by truncating it to the model/context limit.

        If num_ctx is provided we assume it is the model token/context window. If not provided,
        we fall back to a default of 2048 tokens. When the model max tokens is unknown we use
        a conservative heuristic of 1 token = 4 characters.

        Returns the possibly-truncated text to send to the embedding API. The original text
        must remain untouched for storage in ChromaDB.
        """
        try:
            if max_chars is None:
                if num_ctx and isinstance(num_ctx, int) and num_ctx > 0:
                    max_tokens = num_ctx
                else:
                    max_tokens = 2048
                max_chars = self._get_max_embedding_chars(num_ctx)
            else:
                max_tokens = max(1, max_chars // 4)

            if len(text) > max_chars:
                if self.verbose:
                    on_print(f"Truncating text for embedding: original {len(text)} chars > {max_chars} chars (tokens={max_tokens})", Fore.YELLOW)
                return text[:max_chars]
            return text
        except Exception as e:
            # In case of unexpected errors, fall back to original text (do not modify stored docs)
            if self.verbose:
                on_print(f"Error while preparing text for embedding: {e}. Using original text.", Fore.YELLOW)
            return text

    def _sanitize_metadata(self, metadata):
        """Normalize metadata to the scalar value types accepted by ChromaDB."""
        sanitized = {}
        for key, value in metadata.items():
            if value is None:
                continue
            if isinstance(value, (str, int, float, bool)):
                sanitized[key] = value
            else:
                sanitized[key] = str(value)
        return sanitized

    def _offer_long_document_extraction(self, content, embedding_content, num_ctx=None, no_chunking_confirmation=False, document_label=None):
        """Offer an interactive extraction strategy before truncating a long document."""
        if no_chunking_confirmation:
            return embedding_content, None, None

        max_chars = self._get_max_embedding_chars(num_ctx)
        if len(embedding_content) <= max_chars:
            return embedding_content, None, None

        target_label = document_label or "This document"
        on_print(f"\n{target_label} is longer than the embedding context and will be truncated.", Fore.YELLOW)
        on_print("You can choose a more relevant section by providing start and end boundaries for the text to embed.")
        use_extraction = prompt_for_confirmation(
            "Extract a different section before truncation?",
            default=False,
            prompt_label="extract",
            read_fn=on_user_input,
            print_fn=on_print,
        )
        if not use_extraction:
            return embedding_content, None, None

        extract_start = on_user_input("Enter the start boundary for the section to embed: ").strip()
        extract_end = on_user_input("Enter the end boundary for the section to embed (press Enter for end of file): ").strip()

        if not extract_start:
            on_print("Warning: Empty start boundary provided. Falling back to truncation.", Fore.YELLOW)
            return embedding_content, None, None

        if content.find(extract_start) == -1:
            on_print(f"Warning: Start boundary '{extract_start}' was not found. Falling back to truncation.", Fore.YELLOW)
            return embedding_content, None, None

        extract_end = extract_end or None
        extracted_text = self.extract_text_between_strings(content, extract_start, extract_end)
        if not extracted_text:
            on_print("Warning: The selected boundaries produced empty content. Falling back to truncation.", Fore.YELLOW)
            return embedding_content, None, None

        if extract_end:
            on_print(f"Using extracted content between '{extract_start}' and '{extract_end}' for embeddings.", Fore.GREEN)
        else:
            on_print(f"Using extracted content after '{extract_start}' to the end of the document for embeddings.", Fore.GREEN)

        return extracted_text, extract_start, extract_end

    def _should_retry_embedding_with_shorter_prompt(self, text, prompt, current_limit, error):
        if current_limit <= 256 or len(prompt) <= 256:
            return False

        if len(text) > len(prompt):
            return True

        error_text = str(error).lower()
        retry_markers = ("context", "token", "too long", "prompt", "truncate", "length")
        return any(marker in error_text for marker in retry_markers)

    def _generate_embedding_with_retry(self, text, num_ctx=None, target_label=None):
        """Generate an embedding, retrying with a smaller prompt when truncation is still too large."""
        ollama_options = {}
        if num_ctx:
            ollama_options["num_ctx"] = num_ctx

        current_limit = self._get_max_embedding_chars(num_ctx)

        while True:
            embedding_prompt = self._prepare_text_for_embedding(text, num_ctx=num_ctx, max_chars=current_limit)
            try:
                response = ollama.embeddings(
                    prompt=embedding_prompt,
                    model=self.model,
                    options=ollama_options
                )
                return response["embedding"]
            except Exception as e:
                if not self._should_retry_embedding_with_shorter_prompt(text, embedding_prompt, current_limit, e):
                    raise

                next_limit = min(current_limit // 2, len(embedding_prompt) - 1)
                if next_limit < 256:
                    next_limit = 256
                if next_limit >= len(embedding_prompt):
                    raise

                if self.verbose:
                    label = target_label or "document"
                    on_print(
                        f"Embedding failed for {label} at {len(embedding_prompt)} chars: {e}. Retrying with {next_limit} chars.",
                        Fore.YELLOW,
                    )

                current_limit = next_limit

    def _generate_document_id(self, file_path, max_length=63, root_folder=None):
        """
        Generate a unique document ID from a file path.
        
        For HTML/web pages: uses the relative path to the root folder to avoid
        collisions when multiple pages share the same filename (e.g. index.html).
        For all other files: uses the filename without extension (original behavior).
        
        Falls back to an MD5 hash when the ID exceeds max_length.
        
        :param file_path: The absolute path to the file.
        :param max_length: Maximum allowed ID length (ChromaDB limit is 63).
        :return: A unique document ID string.
        """
        # For non-HTML files, use the simple basename (original behavior)
        if not is_html(file_path):
            return os.path.splitext(os.path.basename(file_path))[0]
        
        # For HTML/web pages, use relative path to avoid duplicate filenames
        base_root = root_folder or self.root_folder
        rel_path = os.path.relpath(file_path, base_root)
        
        # Remove file extension
        rel_path_no_ext = os.path.splitext(rel_path)[0]
        
        # Normalize separators and special characters to underscores
        doc_id = re.sub(r'[^\w\-]', '_', rel_path_no_ext)
        
        # Remove leading/trailing underscores and collapse multiple underscores
        doc_id = re.sub(r'_+', '_', doc_id).strip('_')
        
        if len(doc_id) <= max_length:
            return doc_id
        
        # Fallback: use a hash with a readable prefix
        path_hash = hashlib.md5(rel_path.encode('utf-8')).hexdigest()[:16]
        prefix = doc_id[:max_length - 17]  # 16 for hash + 1 for separator
        return f"{prefix}_{path_hash}"

    def _normalize_relative_path(self, file_path, root_folder=None):
        """Return a root-relative path that is stable across operating systems."""
        base_root = root_folder or self.root_folder
        relative_path = os.path.relpath(file_path, base_root)
        return relative_path.replace('\\', '/').replace(os.sep, '/')

    def _build_source_identity(self, file_path, namespace, root_folder=None):
        """Build the stable identity and metadata used by collision-safe IDs."""
        relative_path = self._normalize_relative_path(file_path, root_folder=root_folder)
        identity = f"{namespace}\n{relative_path}"
        return {
            'documentIdStrategy': 'collision-safe',
            'documentNamespace': namespace,
            'documentRelativePath': relative_path,
            'documentSourceKey': hashlib.sha256(identity.encode('utf-8')).hexdigest(),
        }

    def _get_records_for_document_id(self, document_id):
        """Return records using an ID directly or as their parent document ID."""
        if self._document_identity_cache is not None:
            return list(self._document_identity_cache.get(document_id, {}).values())

        records = {}

        def add_result(result):
            if not result:
                return
            ids = result.get('ids', []) or []
            metadatas = result.get('metadatas', []) or []
            for index, record_id in enumerate(ids):
                metadata = metadatas[index] if index < len(metadatas) else {}
                records[record_id] = metadata or {}

        add_result(self.collection.get(ids=[document_id], include=['metadatas']))
        add_result(self.collection.get(
            where={'id': document_id},
            include=['metadatas'],
        ))
        return list(records.values())

    def _prepare_collection_caches(self):
        """Load collection metadata once for cache-aware indexing and reindexing."""
        records = self.collection.get(include=['metadatas'])
        self._document_identity_cache = {}
        self._document_path_cache = {}
        record_ids = records.get('ids', []) or []
        metadatas = records.get('metadatas', []) or []
        for index, record_id in enumerate(record_ids):
            metadata = metadatas[index] if index < len(metadatas) else {}
            self._cache_document_record(record_id, metadata or {})

    def _prepare_document_identity_cache(self):
        """Load collection ownership once for a collision-safe indexing run."""
        self._prepare_collection_caches()

    def _cache_document_identity(self, record_id, metadata):
        """Add an upserted or preloaded record to the collision-safe ownership cache."""
        if self._document_identity_cache is None:
            return
        for document_id in {record_id, metadata.get('id')}:
            if document_id:
                self._document_identity_cache.setdefault(document_id, {})[record_id] = metadata

    def _cache_document_path(self, record_id, metadata):
        """Add an upserted or preloaded record to the file-path cache."""
        if self._document_path_cache is None:
            return
        canonical_path = self._canonicalize_source_path(metadata.get('filePath'))
        if canonical_path:
            self._document_path_cache.setdefault(canonical_path, {})[record_id] = metadata

    def _cache_document_record(self, record_id, metadata):
        self._cache_document_identity(record_id, metadata)
        self._cache_document_path(record_id, metadata)

    def _uncache_document_identity(self, record_id, metadata):
        if self._document_identity_cache is None:
            return
        for document_id in {record_id, metadata.get('id')}:
            if not document_id:
                continue
            cached_records = self._document_identity_cache.get(document_id)
            if not cached_records:
                continue
            cached_records.pop(record_id, None)
            if not cached_records:
                self._document_identity_cache.pop(document_id, None)

    def _uncache_document_path(self, record_id, metadata):
        if self._document_path_cache is None:
            return
        canonical_path = self._canonicalize_source_path(metadata.get('filePath'))
        if not canonical_path:
            return
        cached_records = self._document_path_cache.get(canonical_path)
        if not cached_records:
            return
        cached_records.pop(record_id, None)
        if not cached_records:
            self._document_path_cache.pop(canonical_path, None)

    def _uncache_document_record(self, record_id, metadata):
        self._uncache_document_identity(record_id, metadata)
        self._uncache_document_path(record_id, metadata)

    def _document_id_exists(self, document_id):
        """Check a record ID, using the collision-safe cache when available."""
        if self._document_identity_cache is not None:
            return document_id in self._document_identity_cache.get(document_id, {})
        existing_document = self.collection.get(ids=[document_id])
        return bool(existing_document and existing_document.get('ids', []))

    def _upsert_document(self, documents, metadatas, ids, embeddings=None):
        """Upsert and immediately expose new records to collision-safe ID checks."""
        upsert_args = {
            'documents': documents,
            'metadatas': metadatas,
            'ids': ids,
        }
        if embeddings is not None:
            upsert_args['embeddings'] = embeddings
        self.collection.upsert(**upsert_args)
        for index, record_id in enumerate(ids):
            self._cache_document_record(record_id, metadatas[index])

    def _delete_documents(self, ids):
        """Delete records and keep in-memory caches in sync."""
        if not ids:
            return 0

        existing_records = self.collection.get(ids=ids, include=['metadatas'])
        existing_ids = existing_records.get('ids', []) or []
        existing_metadatas = existing_records.get('metadatas', []) or []
        self.collection.delete(ids=ids)

        for index, record_id in enumerate(existing_ids):
            metadata = existing_metadatas[index] if index < len(existing_metadatas) else {}
            self._uncache_document_record(record_id, metadata or {})

        return len(existing_ids)

    @staticmethod
    def _canonicalize_source_path(file_path):
        if not file_path:
            return None
        return os.path.normcase(os.path.realpath(os.path.abspath(file_path)))

    def _document_id_ownership(self, document_id, source_identity, file_path):
        """Return unused, same, or different for a logical document ID."""
        records = self._get_records_for_document_id(document_id)
        if not records:
            return 'unused'

        expected_source_key = source_identity['documentSourceKey']
        expected_path = self._canonicalize_source_path(file_path)
        for metadata in records:
            existing_source_key = metadata.get('documentSourceKey')
            if existing_source_key:
                if existing_source_key != expected_source_key:
                    return 'different'
            elif self._canonicalize_source_path(metadata.get('filePath')) != expected_path:
                return 'different'
        return 'same'

    def _generate_collision_id(self, legacy_id, source_identity, max_length=63):
        suffix = source_identity['documentSourceKey'][:16]
        separator = '__'
        prefix_length = max_length - len(separator) - len(suffix)
        readable_prefix = legacy_id[:prefix_length] or 'document'
        return f"{readable_prefix}{separator}{suffix}"

    def _resolve_document_id(self, file_path, strategy='legacy', namespace=None, root_folder=None):
        """Resolve a safe logical ID without modifying existing collection records."""
        legacy_id = self._generate_document_id(file_path, root_folder=root_folder)
        if strategy == 'legacy':
            return legacy_id, {}

        source_identity = self._build_source_identity(file_path, namespace, root_folder=root_folder)
        legacy_ownership = self._document_id_ownership(legacy_id, source_identity, file_path)
        if legacy_ownership in ('unused', 'same'):
            return legacy_id, source_identity

        collision_id = self._generate_collision_id(legacy_id, source_identity)
        collision_ownership = self._document_id_ownership(collision_id, source_identity, file_path)
        if collision_ownership == 'different':
            raise ValueError(
                f"Collision-safe document ID '{collision_id}' is already owned by another source"
            )

        if self.verbose:
            on_print(
                f"Document ID collision for {legacy_id}; using {collision_id} for "
                f"{source_identity['documentRelativePath']}",
                Fore.YELLOW,
            )
        return collision_id, source_identity

    @staticmethod
    def _is_supported_text_file(file_path):
        supported_extensions = (".txt", ".md", ".tex", ".pdf", ".docx", ".pptx", ".xlsx", ".csv")
        return file_path.lower().endswith(supported_extensions) or is_html(file_path)

    def get_text_files(self, root_path=None):
        """
        Recursively find all supported files in the provided path.
        Also include HTML files without extensions if they start with <!DOCTYPE html> or <html.
        Ignore empty lines at the beginning of the file and check only the first non-empty line.
        """
        text_files = []
        search_root = root_path or self.root_folder

        if os.path.isfile(search_root):
            return [search_root] if self._is_supported_text_file(search_root) else []

        for root, dirs, files in os.walk(search_root):
            for file in files:
                file_path = os.path.join(root, file)
                if self._is_supported_text_file(file_path):
                    text_files.append(file_path)
        return text_files

    def read_file(self, file_path):
        """
        Read the content of a file.
        Supports plain text, PDF, DOCX, PPTX, and XLSX files.
        """
        try:
            lower_path = file_path.lower()

            # Handle PDF files
            if lower_path.endswith('.pdf'):
                reader = PdfReader(file_path)
                text = ''
                for page in reader.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text
                return re.sub(r'\n+', '\n', text)

            # Handle DOCX files
            if lower_path.endswith('.docx'):
                return extract_text_from_docx(file_path)

            # Handle PPTX files
            if lower_path.endswith('.pptx'):
                return extract_text_from_pptx(file_path)

            # Handle XLSX files
            if lower_path.endswith('.xlsx'):
                return extract_text_from_xlsx(file_path)

            # Handle CSV files
            if lower_path.endswith('.csv'):
                return extract_text_from_csv(file_path)

            # Default: read as text
            with open(file_path, 'r', encoding='utf-8') as file:
                return file.read()
        except Exception as e:
            if self.verbose:
                on_print(f"Error reading file {file_path}: {e}", Fore.RED)
            return None

    def extract_text_between_strings(self, content, start_string, end_string):
        """
        Extract text between two specified strings.
        
        :param content: The full text content.
        :param start_string: The string marking the start of extraction.
        :param end_string: The string marking the end of extraction. If omitted,
                           extraction continues to the end of the document.
        :return: The extracted text, or the full content if strings are not found.
        """
        if not start_string:
            return content
            
        start_index = content.find(start_string)
        if start_index == -1:
            if self.verbose:
                on_print(f"Start string '{start_string}' not found, using full content", Fore.YELLOW)
            return content
            
        # Move past the start string
        start_index += len(start_string)

        if not end_string:
            extracted_text = content[start_index:]
            if self.verbose:
                on_print(
                    f"Extracted {len(extracted_text)} characters from '{start_string}' to the end of the document",
                    Fore.WHITE + Style.DIM,
                )
            return extracted_text
        
        end_index = content.find(end_string, start_index)
        if end_index == -1:
            if self.verbose:
                on_print(f"End string '{end_string}' not found after start string, using content from start string to end", Fore.YELLOW)
            return content[start_index:]
            
        extracted_text = content[start_index:end_index]
        
        if self.verbose:
            on_print(f"Extracted {len(extracted_text)} characters between '{start_string}' and '{end_string}'", Fore.WHITE + Style.DIM)
            
        return extracted_text

    def _validate_document_identity_settings(self, document_id_strategy, document_id_namespace):
        if document_id_strategy not in ('legacy', 'collision-safe'):
            raise ValueError("document_id_strategy must be 'legacy' or 'collision-safe'")
        if document_id_strategy == 'collision-safe':
            document_id_namespace = (document_id_namespace or '').strip()
            if not document_id_namespace:
                raise ValueError("document_id_namespace is required with collision-safe document IDs")
        return document_id_strategy, document_id_namespace

    def _build_file_metadata(self, file_path, document_id, source_identity, additional_metadata, split_paragraphs, add_summary, store_full_docs):
        file_name = os.path.basename(file_path)
        file_name_without_ext = os.path.splitext(file_name)[0]
        current_date = datetime.now().isoformat()

        file_metadata = {
            'published': current_date,
            'docSource': os.path.dirname(file_path),
            'docAuthor': 'Unknown',
            'description': f"Document from {file_path}",
            'title': file_name_without_ext,
            'id': document_id,
            'filePath': file_path,
            'splitParagraphs': split_paragraphs,
            'addSummary': add_summary,
            'store_full_docs': bool(store_full_docs),
        }
        file_metadata.update(source_identity)

        file_metadata['url'] = urljoin("file://", file_path)
        if os.name == 'nt':
            file_metadata['url'] = file_metadata['url'].replace("\\", "/")
            file_metadata['url'] = file_metadata['url'].replace("file://", "file:///")

        if additional_metadata and file_path in additional_metadata:
            file_metadata.update(additional_metadata[file_path])

        return file_metadata

    def _split_content_for_indexing(self, file_path, content_to_chunk, split_paragraphs, text_splitter):
        lower_file_path = file_path.lower()
        is_tabular_content = (
            lower_file_path.endswith('.csv') or
            lower_file_path.endswith('.xlsx')
        )
        is_markdown_content = (
            is_markdown(file_path) or
            lower_file_path.endswith('.docx') or
            lower_file_path.endswith('.pptx')
        )

        if is_tabular_content:
            tabular_splitter = TabularDataSplitter(content_to_chunk, rows_per_chunk=50)
            chunks = tabular_splitter.split()
        elif is_html(file_path):
            markdown_splitter = MarkdownSplitter(extract_text_from_html(content_to_chunk), split_paragraphs=split_paragraphs)
            chunks = markdown_splitter.split()
        elif is_markdown_content:
            markdown_splitter = MarkdownSplitter(content_to_chunk, split_paragraphs=split_paragraphs)
            chunks = markdown_splitter.split()
        else:
            chunks = text_splitter.split_text(content_to_chunk)

        return chunks, is_tabular_content

    def _maybe_generate_document_summary(self, file_name, content_to_chunk, document_id, add_summary, no_chunking_confirmation, num_ctx, is_tabular_content):
        if not add_summary:
            return None

        summary_model = self.summary_model
        if summary_model is None:
            try:
                summary_model = state.current_model
            except NameError:
                summary_model = None
        if not summary_model:
            return None

        if is_tabular_content:
            table_header_line = ""
            table_first_row = ""
            all_lines = content_to_chunk.splitlines()
            for index, line in enumerate(all_lines):
                if line.startswith('|') and index + 1 < len(all_lines):
                    next_line = all_lines[index + 1]
                    if re.match(r'^\|\s*-{3,}', next_line):
                        table_header_line = line
                        if index + 2 < len(all_lines) and all_lines[index + 2].startswith('|'):
                            table_first_row = all_lines[index + 2]
                        break

            user_context = ""
            if not no_chunking_confirmation:
                on_print(f"\nTabular file detected: {file_name}", Fore.CYAN)
                if table_header_line:
                    on_print(f"Columns : {table_header_line}", Fore.WHITE + Style.DIM)
                if table_first_row:
                    on_print(f"First row: {table_first_row}", Fore.WHITE + Style.DIM)
                on_print("Auto-generated summaries for tabular data are usually not meaningful.")
                user_context = on_user_input(
                    "Provide context about what this data represents (press Enter to skip summary): "
                ).strip()

            if not user_context:
                if self.verbose:
                    on_print(f"Skipping summary for tabular document {document_id} (no context provided)", Fore.WHITE + Style.DIM)
                return None

            tabular_info = ""
            if table_header_line:
                tabular_info += f"\nColumn headers: {table_header_line}"
            if table_first_row:
                tabular_info += f"\nFirst data row: {table_first_row}"
            if self.verbose:
                on_print(f"Generating context-enhanced summary for {document_id}", Fore.WHITE + Style.DIM)
            summary_prompt = (
                f"A user provided the following context about a tabular data file:\n"
                f"{user_context}\n"
                f"{tabular_info}\n\n"
                f"Based on this information, write a concise summary (2-5 sentences) describing "
                f"what this dataset contains, what each column likely represents, and what kind "
                f"of queries it would be useful to answer."
            )
            try:
                summary_response = self._ask_fn(
                    "You are a helpful assistant that creates concise, informative dataset summaries.",
                    summary_prompt,
                    summary_model,
                    temperature=0.3,
                    no_bot_prompt=True,
                    stream_active=False,
                    num_ctx=num_ctx
                )
                if self.verbose:
                    on_print(f"Summary generated: {summary_response.strip()}", Fore.GREEN)
                return f"[Document Summary: {summary_response.strip()}]\n\n"
            except Exception as e:
                if self.verbose:
                    on_print(f"Failed to generate summary: {e}", Fore.YELLOW)
                return None

        if self.verbose:
            on_print(f"Generating summary for document {document_id} using model: {summary_model}", Fore.WHITE + Style.DIM)
        summary_prompt = f"""Provide a brief summary (2-5 sentences) of the following document. Focus on the main topic and key points:

{content_to_chunk[:2000]}"""
        try:
            summary_response = self._ask_fn(
                "You are a helpful assistant that creates concise document summaries.",
                summary_prompt,
                summary_model,
                temperature=0.3,
                no_bot_prompt=True,
                stream_active=False,
                num_ctx=num_ctx
            )
            if self.verbose:
                on_print(f"Summary generated: {summary_response.strip()}", Fore.GREEN)
            return f"[Document Summary: {summary_response.strip()}]\n\n"
        except Exception as e:
            if self.verbose:
                on_print(f"Failed to generate summary: {e}", Fore.YELLOW)
            return None

    def _index_file(self, file_path, allow_chunks=True, no_chunking_confirmation=False, split_paragraphs=False, additional_metadata=None, num_ctx=None, skip_existing=True, extract_start=None, extract_end=None, add_summary=True, store_full_docs=False, document_id_strategy='legacy', document_id_namespace=None, source_root=None, forced_document_id=None, forced_source_identity=None, text_splitter=None):
        try:
            if forced_document_id is not None:
                document_id = forced_document_id
                source_identity = forced_source_identity or {}
            else:
                document_id, source_identity = self._resolve_document_id(
                    file_path,
                    strategy=document_id_strategy,
                    namespace=document_id_namespace,
                    root_folder=source_root,
                )

            if not allow_chunks and skip_existing and self._document_id_exists(document_id):
                if self.verbose:
                    on_print(f"Skipping existing document: {document_id}", Fore.WHITE + Style.DIM)
                return 'skipped'

            content = self.read_file(file_path)
            if not content:
                on_print(f"An error occurred while reading file: {file_path}", Fore.RED)
                return 'error'

            file_metadata = self._build_file_metadata(
                file_path,
                document_id,
                source_identity,
                additional_metadata,
                split_paragraphs,
                add_summary,
                store_full_docs,
            )

            embedding_content = content
            if extract_start:
                embedding_content = self.extract_text_between_strings(content, extract_start, extract_end)
                file_metadata['extraction_used'] = True
                file_metadata['extract_start'] = extract_start
                file_metadata['extract_end'] = extract_end
                file_metadata['extracted_length'] = len(embedding_content)
                file_metadata['original_length'] = len(content)

            file_metadata = self._sanitize_metadata(file_metadata)

            if allow_chunks:
                chunks, is_tabular_content = self._split_content_for_indexing(
                    file_path,
                    embedding_content,
                    split_paragraphs,
                    text_splitter,
                )

                if skip_existing and chunks:
                    all_chunk_ids = [f"{document_id}_{index}" for index in range(len(chunks))]
                    if self._document_identity_cache is not None:
                        existing_ids_set = {
                            chunk_id for chunk_id in all_chunk_ids
                            if self._document_id_exists(chunk_id)
                        }
                    else:
                        existing_chunks = self.collection.get(ids=all_chunk_ids)
                        existing_ids_set = set(existing_chunks.get('ids', []))
                    if existing_ids_set == set(all_chunk_ids):
                        if self.verbose:
                            on_print(f"Skipping fully indexed document: {document_id} ({len(chunks)} chunks)", Fore.WHITE + Style.DIM)
                        return 'skipped'

                document_summary = self._maybe_generate_document_summary(
                    os.path.basename(file_path),
                    embedding_content,
                    document_id,
                    add_summary,
                    no_chunking_confirmation,
                    num_ctx,
                    is_tabular_content,
                )

                for index, chunk in enumerate(chunks):
                    chunk_id = f"{document_id}_{index}"
                    if skip_existing and self._document_id_exists(chunk_id):
                        if self.verbose:
                            on_print(f"Skipping existing chunk: {chunk_id}", Fore.WHITE + Style.DIM)
                        continue

                    chunk_with_summary = document_summary + chunk if document_summary else chunk
                    embedding = None
                    if self.model:
                        if self.verbose:
                            embedding_info = "using extracted text" if file_metadata.get('extraction_used') else "using full content"
                            summary_info = " with summary" if document_summary else ""
                            on_print(f"Generating embedding for chunk {chunk_id} using {self.model} ({embedding_info}{summary_info})", Fore.WHITE + Style.DIM)
                        embedding = self._generate_embedding_with_retry(
                            chunk_with_summary,
                            num_ctx=num_ctx,
                            target_label=f"chunk {chunk_id}",
                        )

                    chunk_metadata = file_metadata.copy()
                    chunk_metadata['chunk_index'] = index
                    if document_summary:
                        chunk_metadata['has_summary'] = True

                    stored_document = content if store_full_docs else chunk_with_summary
                    if embedding:
                        self._upsert_document(
                            documents=[stored_document],
                            metadatas=[chunk_metadata],
                            ids=[chunk_id],
                            embeddings=[embedding]
                        )
                    else:
                        self._upsert_document(
                            documents=[stored_document],
                            metadatas=[chunk_metadata],
                            ids=[chunk_id]
                        )
                return 'indexed'

            embedding = None
            if self.model:
                if not extract_start:
                    embedding_content, long_doc_extract_start, long_doc_extract_end = self._offer_long_document_extraction(
                        content,
                        embedding_content,
                        num_ctx=num_ctx,
                        no_chunking_confirmation=no_chunking_confirmation,
                        document_label=f"Document {document_id}",
                    )
                    if long_doc_extract_start:
                        file_metadata['extraction_used'] = True
                        file_metadata['extract_start'] = long_doc_extract_start
                        file_metadata['extract_end'] = long_doc_extract_end
                        file_metadata['extracted_length'] = len(embedding_content)
                        file_metadata['original_length'] = len(content)
                        file_metadata = self._sanitize_metadata(file_metadata)

                if self.verbose:
                    embedding_info = "using extracted text" if file_metadata.get('extraction_used') else "using full content"
                    on_print(f"Generating embedding for document {document_id} using {self.model} ({embedding_info})", Fore.WHITE + Style.DIM)

                embedding = self._generate_embedding_with_retry(
                    embedding_content,
                    num_ctx=num_ctx,
                    target_label=f"document {document_id}",
                )

            if embedding:
                self._upsert_document(
                    documents=[content],
                    metadatas=[file_metadata],
                    ids=[document_id],
                    embeddings=[embedding]
                )
            else:
                self._upsert_document(
                    documents=[content],
                    metadatas=[file_metadata],
                    ids=[document_id]
                )
            return 'indexed'
        except KeyboardInterrupt:
            raise
        except Exception as e:
            on_print(f"Error processing file {file_path}: {e}", Fore.RED)
            return 'error'

    def _collect_existing_file_records(self, file_path):
        canonical_path = self._canonicalize_source_path(file_path)
        if self._document_path_cache is not None:
            return list(self._document_path_cache.get(canonical_path, {}).items())

        records = {}
        direct_records = self.collection.get(where={'filePath': file_path}, include=['metadatas'])
        direct_ids = direct_records.get('ids', []) or []
        direct_metadatas = direct_records.get('metadatas', []) or []
        for index, record_id in enumerate(direct_ids):
            metadata = direct_metadatas[index] if index < len(direct_metadatas) else {}
            records[record_id] = metadata or {}

        if records:
            return list(records.items())

        all_records = self.collection.get(include=['metadatas'])
        record_ids = all_records.get('ids', []) or []
        metadatas = all_records.get('metadatas', []) or []
        for index, record_id in enumerate(record_ids):
            metadata = metadatas[index] if index < len(metadatas) else {}
            if self._canonicalize_source_path((metadata or {}).get('filePath')) == canonical_path:
                records[record_id] = metadata or {}
        return list(records.items())

    def _resolve_reindex_options(self, file_records, allow_chunks, split_paragraphs, extract_start, extract_end, add_summary, store_full_docs, document_id_strategy, document_id_namespace):
        record_ids = [record_id for record_id, _ in file_records]
        metadatas = [metadata or {} for _, metadata in file_records]
        representative_metadata = metadatas[0] if metadatas else {}
        source_identity = {}
        if representative_metadata.get('documentIdStrategy') == 'collision-safe':
            for key in ('documentIdStrategy', 'documentNamespace', 'documentRelativePath', 'documentSourceKey'):
                value = representative_metadata.get(key)
                if value is not None:
                    source_identity[key] = value

        resolved_options = {
            'allow_chunks': any('chunk_index' in metadata for metadata in metadatas) if metadatas else allow_chunks,
            'split_paragraphs': representative_metadata.get('splitParagraphs', split_paragraphs),
            'extract_start': representative_metadata.get('extract_start', extract_start),
            'extract_end': representative_metadata.get('extract_end', extract_end),
            'add_summary': representative_metadata.get('addSummary', add_summary),
            'store_full_docs': representative_metadata.get('store_full_docs', store_full_docs),
            'document_id_strategy': representative_metadata.get('documentIdStrategy', document_id_strategy or 'legacy'),
            'document_id_namespace': representative_metadata.get('documentNamespace', document_id_namespace),
            'forced_document_id': representative_metadata.get('id') or (record_ids[0] if record_ids else None),
            'forced_source_identity': source_identity,
        }
        return record_ids, representative_metadata, resolved_options

    def reindex_document(self, file_path, allow_chunks=True, no_chunking_confirmation=True, split_paragraphs=False, additional_metadata=None, num_ctx=None, extract_start=None, extract_end=None, add_summary=True, store_full_docs=False, document_id_strategy='legacy', document_id_namespace=None, source_root=None, prepare_caches=True):
        file_path = os.path.abspath(file_path)
        if not os.path.isfile(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
        if not self._is_supported_text_file(file_path):
            raise ValueError(f"Unsupported file type for reindexing: {file_path}")

        document_id_strategy, document_id_namespace = self._validate_document_identity_settings(
            document_id_strategy,
            document_id_namespace,
        )

        if prepare_caches:
            self._prepare_collection_caches()

        file_records = self._collect_existing_file_records(file_path)
        deleted_record_ids, representative_metadata, resolved_options = self._resolve_reindex_options(
            file_records,
            allow_chunks,
            split_paragraphs,
            extract_start,
            extract_end,
            add_summary,
            store_full_docs,
            document_id_strategy,
            document_id_namespace,
        )

        deleted_count = self._delete_documents(deleted_record_ids) if deleted_record_ids else 0
        reindex_root = source_root or os.path.dirname(file_path)
        text_splitter = None
        if resolved_options['allow_chunks']:
            from langchain_text_splitters import RecursiveCharacterTextSplitter
            text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)

        status = self._index_file(
            file_path,
            allow_chunks=resolved_options['allow_chunks'],
            no_chunking_confirmation=no_chunking_confirmation,
            split_paragraphs=resolved_options['split_paragraphs'],
            additional_metadata=additional_metadata,
            num_ctx=num_ctx,
            skip_existing=False,
            extract_start=resolved_options['extract_start'],
            extract_end=resolved_options['extract_end'],
            add_summary=resolved_options['add_summary'],
            store_full_docs=resolved_options['store_full_docs'],
            document_id_strategy=resolved_options['document_id_strategy'],
            document_id_namespace=resolved_options['document_id_namespace'],
            source_root=reindex_root,
            forced_document_id=resolved_options['forced_document_id'],
            forced_source_identity=resolved_options['forced_source_identity'],
            text_splitter=text_splitter,
        )

        action = 'updated' if deleted_count else 'added'
        return {
            'action': action,
            'deleted': deleted_count,
            'status': status,
            'filePath': file_path,
            'documentId': resolved_options['forced_document_id'],
            'existingMetadata': representative_metadata,
        }

    def reindex_path(self, path, allow_chunks=True, no_chunking_confirmation=True, split_paragraphs=False, additional_metadata=None, num_ctx=None, extract_start=None, extract_end=None, add_summary=True, store_full_docs=False, document_id_strategy='legacy', document_id_namespace=None):
        path = os.path.abspath(path)
        if not os.path.exists(path):
            raise FileNotFoundError(f"Path not found: {path}")

        document_id_strategy, document_id_namespace = self._validate_document_identity_settings(
            document_id_strategy,
            document_id_namespace,
        )
        self._prepare_collection_caches()

        if os.path.isfile(path):
            result = self.reindex_document(
                path,
                allow_chunks=allow_chunks,
                no_chunking_confirmation=no_chunking_confirmation,
                split_paragraphs=split_paragraphs,
                additional_metadata=additional_metadata,
                num_ctx=num_ctx,
                extract_start=extract_start,
                extract_end=extract_end,
                add_summary=add_summary,
                store_full_docs=store_full_docs,
                document_id_strategy=document_id_strategy,
                document_id_namespace=document_id_namespace,
                source_root=os.path.dirname(path),
                prepare_caches=False,
            )
            return {
                'processed': 1,
                'updated': 1 if result['action'] == 'updated' and result['status'] == 'indexed' else 0,
                'added': 1 if result['action'] == 'added' and result['status'] == 'indexed' else 0,
                'errors': 1 if result['status'] == 'error' else 0,
                'files': [result],
            }

        text_files = self.get_text_files(path)
        if not text_files:
            return {
                'processed': 0,
                'updated': 0,
                'added': 0,
                'errors': 0,
                'files': [],
            }

        progress_bar = None
        if self.verbose:
            progress_bar = tqdm(total=len(text_files), desc="Reindexing files", unit="file", bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt}")

        results = []
        updated = 0
        added = 0
        errors = 0
        for file_path in text_files:
            if progress_bar:
                progress_bar.update(1)

            result = self.reindex_document(
                file_path,
                allow_chunks=allow_chunks,
                no_chunking_confirmation=no_chunking_confirmation,
                split_paragraphs=split_paragraphs,
                additional_metadata=additional_metadata,
                num_ctx=num_ctx,
                extract_start=extract_start,
                extract_end=extract_end,
                add_summary=add_summary,
                store_full_docs=store_full_docs,
                document_id_strategy=document_id_strategy,
                document_id_namespace=document_id_namespace,
                source_root=path,
                prepare_caches=False,
            )
            results.append(result)
            if result['status'] == 'error':
                errors += 1
            elif result['action'] == 'updated':
                updated += 1
            else:
                added += 1

        if progress_bar:
            progress_bar.close()

        return {
            'processed': len(text_files),
            'updated': updated,
            'added': added,
            'errors': errors,
            'files': results,
        }

    def index_documents(self, allow_chunks=True, no_chunking_confirmation=False, split_paragraphs=False, additional_metadata=None, num_ctx=None, skip_existing=True, extract_start=None, extract_end=None, add_summary=True, store_full_docs=None, document_id_strategy='legacy', document_id_namespace=None):
        """
        Index all text files in the root folder.

        :param allow_chunks: Whether to chunk large documents.
        :param no_chunking_confirmation: Skip confirmation for chunking and extraction prompts.
        :param split_paragraphs: Whether to split markdown content into paragraphs.
        :param additional_metadata: Optional dictionary to pass additional metadata by file name.
        :param skip_existing: Whether to skip indexing if a document/chunk with the same ID already exists.
        :param extract_start: Optional string marking the start of the text to extract for embedding computation.
        :param extract_end: Optional string marking the end of the text to extract for embedding computation.
        :param add_summary: Whether to generate and prepend a summary to each chunk (default: True).
        :param store_full_docs: Whether to store the full document content for each chunk in chunking mode.
                                Embeddings are still computed from chunks. If None and not in automated mode, the user is prompted.
        :param document_id_strategy: ``legacy`` uses filename-based IDs. ``collision-safe``
                                     disambiguates different source paths without replacing existing records.
        :param document_id_namespace: Stable dataset name used with ``collision-safe`` IDs.
        """
        document_id_strategy, document_id_namespace = self._validate_document_identity_settings(
            document_id_strategy,
            document_id_namespace,
        )
        if document_id_strategy == 'collision-safe':
            self._prepare_document_identity_cache()
        else:
            self._document_identity_cache = None
            self._document_path_cache = None

        if allow_chunks and not no_chunking_confirmation:
            on_print("Large documents will be chunked into smaller pieces for indexing.")
            allow_chunks = prompt_for_confirmation(
                "Continue with chunking?",
                default=True,
                prompt_label="chunking",
                read_fn=on_user_input,
                print_fn=on_print,
            )

        if extract_start is None and extract_end is None and not no_chunking_confirmation:
            on_print("\nOptional: You can extract only a specific part of each document for embedding computation.")
            on_print("This allows you to focus on relevant sections while still storing the full document.")
            use_extraction = prompt_for_confirmation(
                "Extract specific text sections for embeddings?",
                default=False,
                prompt_label="extract",
                read_fn=on_user_input,
                print_fn=on_print,
            )

            if use_extraction:
                extract_start = on_user_input("Enter the start string (text that marks the beginning of the section): ").strip()
                extract_end = on_user_input("Enter the end string (text that marks the end of the section): ").strip()

                if not extract_start:
                    on_print("Warning: Empty start string provided. Text extraction will be disabled.", Fore.YELLOW)
                    extract_start = None
                    extract_end = None
                elif not extract_end:
                    extract_end = None
                    on_print(
                        f"Text extraction enabled: extracting content after '{extract_start}' to the end of each document",
                        Fore.GREEN,
                    )
                else:
                    on_print(f"Text extraction enabled: extracting content between '{extract_start}' and '{extract_end}'", Fore.GREEN)

        if allow_chunks and store_full_docs is None and not no_chunking_confirmation:
            on_print("\nOptional: You can store the full original document for each chunk instead of just the chunk text.")
            on_print("Embeddings will still be computed from chunks only, but retrieved results will contain the complete document.")
            store_full_docs = prompt_for_confirmation(
                "Store the full document for each chunk?",
                default=False,
                prompt_label="storage",
                read_fn=on_user_input,
                print_fn=on_print,
            )
            if store_full_docs:
                on_print("Full document storage enabled: each chunk will store the complete original document.", Fore.GREEN)

        if store_full_docs is None:
            store_full_docs = False

        text_splitter = None
        if allow_chunks:
            from langchain_text_splitters import RecursiveCharacterTextSplitter
            text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)

        text_files = self.get_text_files()

        progress_bar = None
        if self.verbose:
            progress_bar = tqdm(total=len(text_files), desc="Indexing files", unit="file", bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt}")

        for file_path in text_files:
            if progress_bar:
                progress_bar.update(1)

            try:
                status = self._index_file(
                    file_path,
                    allow_chunks=allow_chunks,
                    no_chunking_confirmation=no_chunking_confirmation,
                    split_paragraphs=split_paragraphs,
                    additional_metadata=additional_metadata,
                    num_ctx=num_ctx,
                    skip_existing=skip_existing,
                    extract_start=extract_start,
                    extract_end=extract_end,
                    add_summary=add_summary,
                    store_full_docs=store_full_docs,
                    document_id_strategy=document_id_strategy,
                    document_id_namespace=document_id_namespace,
                    source_root=self.root_folder,
                    text_splitter=text_splitter,
                )
                if status == 'skipped':
                    continue
            except KeyboardInterrupt:
                if progress_bar:
                    progress_bar.close()
                break
            except Exception as e:
                on_print(f"Error processing file {file_path}: {e}", Fore.RED)
                continue

        if progress_bar:
            progress_bar.close()
