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

        if verbose:
            on_print(f"DocumentIndexer initialized with embedding model: {self.model}", Fore.WHITE + Style.DIM)
            if self.summary_model:
                on_print(f"Using summary model: {self.summary_model}", Fore.WHITE + Style.DIM)
            on_print(f"Using collection: {self.collection.name}", Fore.WHITE + Style.DIM)
            on_print(f"Verbose mode is {'on' if self.verbose else 'off'}", Fore.WHITE + Style.DIM)
            on_print(f"Using embeddings model: {self.model}", Fore.WHITE + Style.DIM)

    def _prepare_text_for_embedding(self, text, num_ctx=None):
        """
        Prepare text to send to the embedding model by truncating it to the model/context limit.

        If num_ctx is provided we assume it is the model token/context window. If not provided,
        we fall back to a default of 2048 tokens. When the model max tokens is unknown we use
        a conservative heuristic of 1 token = 4 characters.

        Returns the possibly-truncated text to send to the embedding API. The original text
        must remain untouched for storage in ChromaDB.
        """
        try:
            if num_ctx and isinstance(num_ctx, int) and num_ctx > 0:
                max_tokens = num_ctx
            else:
                # Default context window if not specified
                max_tokens = 2048

            # Heuristic: 1 token ~= 4 characters
            max_chars = max_tokens * 4

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

    def _generate_document_id(self, file_path, max_length=63):
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
        rel_path = os.path.relpath(file_path, self.root_folder)
        
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

    def get_text_files(self):
        """
        Recursively find all .txt, .md, .tex, .pdf, .docx, .pptx, .xlsx files in the root folder.
        Also include HTML files without extensions if they start with <!DOCTYPE html> or <html.
        Ignore empty lines at the beginning of the file and check only the first non-empty line.
        """
        text_files = []
        supported_extensions = (".txt", ".md", ".tex", ".pdf", ".docx", ".pptx", ".xlsx", ".csv")
        for root, dirs, files in os.walk(self.root_folder):
            for file in files:
                # Check for files with extension
                if file.lower().endswith(supported_extensions):
                    text_files.append(os.path.join(root, file))
                else:
                    # Check for HTML files without extensions
                    file_path = os.path.join(root, file)
                    if is_html(file_path):
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
        :param end_string: The string marking the end of extraction.
        :return: The extracted text, or the full content if strings are not found.
        """
        if not start_string or not end_string:
            return content
            
        start_index = content.find(start_string)
        if start_index == -1:
            if self.verbose:
                on_print(f"Start string '{start_string}' not found, using full content", Fore.YELLOW)
            return content
            
        # Move past the start string
        start_index += len(start_string)
        
        end_index = content.find(end_string, start_index)
        if end_index == -1:
            if self.verbose:
                on_print(f"End string '{end_string}' not found after start string, using content from start string to end", Fore.YELLOW)
            return content[start_index:]
            
        extracted_text = content[start_index:end_index]
        
        if self.verbose:
            on_print(f"Extracted {len(extracted_text)} characters between '{start_string}' and '{end_string}'", Fore.WHITE + Style.DIM)
            
        return extracted_text

    def index_documents(self, allow_chunks=True, no_chunking_confirmation=False, split_paragraphs=False, additional_metadata=None, num_ctx=None, skip_existing=True, extract_start=None, extract_end=None, add_summary=True, store_full_docs=None):
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
        """
        # Ask the user to confirm if they want to allow chunking of large documents
        if allow_chunks and not no_chunking_confirmation:
            on_print("Large documents will be chunked into smaller pieces for indexing.")
            allow_chunks = on_user_input("Do you want to continue with chunking (if you answer 'no', large documents will be indexed as a whole)? [y/n]: ").lower() in ['y', 'yes']

        # Ask the user for extraction strings if not provided
        # Skip asking if no_chunking_confirmation is True (automated indexing)
        if extract_start is None and extract_end is None and not no_chunking_confirmation:
            on_print("\nOptional: You can extract only a specific part of each document for embedding computation.")
            on_print("This allows you to focus on relevant sections while still storing the full document.")
            use_extraction = on_user_input("Do you want to extract specific text sections for embedding? [y/n]: ").lower() in ['y', 'yes']
            
            if use_extraction:
                extract_start = on_user_input("Enter the start string (text that marks the beginning of the section): ").strip()
                extract_end = on_user_input("Enter the end string (text that marks the end of the section): ").strip()
                
                if not extract_start or not extract_end:
                    on_print("Warning: Empty start or end string provided. Text extraction will be disabled.", Fore.YELLOW)
                    extract_start = None
                    extract_end = None
                else:
                    on_print(f"Text extraction enabled: extracting content between '{extract_start}' and '{extract_end}'", Fore.GREEN)

        # Ask the user whether to store full documents per chunk in chunking mode
        if allow_chunks and store_full_docs is None and not no_chunking_confirmation:
            on_print("\nOptional: You can store the full original document for each chunk instead of just the chunk text.")
            on_print("Embeddings will still be computed from chunks only, but retrieved results will contain the complete document.")
            store_full_docs = on_user_input("Do you want to store the full document for each chunk? [y/n]: ").lower() in ['y', 'yes']
            if store_full_docs:
                on_print("Full document storage enabled: each chunk will store the complete original document.", Fore.GREEN)
        
        # Default to False if not set (automated mode without explicit flag)
        if store_full_docs is None:
            store_full_docs = False

        if allow_chunks:
            from langchain_text_splitters import RecursiveCharacterTextSplitter

        # Get the list of text files
        text_files = self.get_text_files()

        if allow_chunks:
            text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)

        progress_bar = None
        if self.verbose:
            # Progress bar for indexing
            progress_bar = tqdm(total=len(text_files), desc="Indexing files", unit="file", bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt}")

        for file_path in text_files:
            if progress_bar:
                progress_bar.update(1)

            try:
                document_id = self._generate_document_id(file_path)

                # Check if skipping existing documents and if the document ID exists (for non-chunked case)
                if not allow_chunks and skip_existing:
                    existing_doc = self.collection.get(ids=[document_id])
                    if existing_doc and len(existing_doc.get('ids', [])) > 0:
                        if self.verbose:
                            on_print(f"Skipping existing document: {document_id}", Fore.WHITE + Style.DIM)
                        continue

                content = self.read_file(file_path)

                if not content:
                    on_print(f"An error occurred while reading file: {file_path}", Fore.RED)
                    continue
                
                # Add any additional metadata for the file
                # Extract file name and base file information
                file_name = os.path.basename(file_path)
                file_name_without_ext = os.path.splitext(file_name)[0]
                current_date = datetime.now().isoformat()
                
                # Create a more comprehensive metadata structure
                file_metadata = {
                    'published': current_date,
                    'docSource': os.path.dirname(file_path),
                    'docAuthor': 'Unknown',
                    'description': f"Document from {file_path}",
                    'title': file_name_without_ext,
                    'id': document_id,
                    'filePath': file_path
                }
                
                # Convert the file path to url and add it to the metadata
                file_metadata['url'] = urljoin("file://", file_path)
                
                # If windows, convert the file path to a URI
                if os.name == 'nt':
                    file_metadata['url'] = file_metadata['url'].replace("\\", "/")
                    
                    # Replace the drive letter with "file:///" prefix
                    file_metadata['url'] = file_metadata['url'].replace("file://", "file:///")
                
                if additional_metadata and file_path in additional_metadata:
                    file_metadata.update(additional_metadata[file_path])

                # Extract text for embedding if start and end strings are provided
                embedding_content = content
                if extract_start and extract_end:
                    embedding_content = self.extract_text_between_strings(content, extract_start, extract_end)
                    # Add metadata to indicate partial extraction was used
                    file_metadata['extraction_used'] = True
                    file_metadata['extract_start'] = extract_start
                    file_metadata['extract_end'] = extract_end
                    file_metadata['extracted_length'] = len(embedding_content)
                    file_metadata['original_length'] = len(content)

                if allow_chunks:
                    chunks = []
                    # Use embedding_content for chunking (which may be extracted text)
                    content_to_chunk = embedding_content
                    
                    # Split Markdown files into sections if needed
                    # DOCX, PPTX, and XLSX are extracted as Markdown, so use MarkdownSplitter for them too
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
                        # Use TabularDataSplitter to chunk by rows while
                        # repeating the header on each chunk for context
                        tabular_splitter = TabularDataSplitter(content_to_chunk, rows_per_chunk=50)
                        chunks = tabular_splitter.split()
                    elif is_html(file_path):
                        # Convert to Markdown before splitting
                        markdown_splitter = MarkdownSplitter(extract_text_from_html(content_to_chunk), split_paragraphs=split_paragraphs)
                        chunks = markdown_splitter.split()
                    elif is_markdown_content:
                        markdown_splitter = MarkdownSplitter(content_to_chunk, split_paragraphs=split_paragraphs)
                        chunks = markdown_splitter.split()
                    else:
                        chunks = text_splitter.split_text(content_to_chunk)
                    
                    # When skip_existing is enabled, check upfront if ALL chunks already
                    # exist in the collection. This avoids the expensive LLM summary
                    # generation for documents that are already fully indexed.
                    if skip_existing and chunks:
                        all_chunk_ids = [f"{document_id}_{i}" for i in range(len(chunks))]
                        existing_chunks = self.collection.get(ids=all_chunk_ids)
                        existing_ids_set = set(existing_chunks.get('ids', []))
                        if existing_ids_set == set(all_chunk_ids):
                            if self.verbose:
                                on_print(f"Skipping fully indexed document: {document_id} ({len(chunks)} chunks)", Fore.WHITE + Style.DIM)
                            continue
                    
                    # Generate document summary once if add_summary is enabled
                    document_summary = None
                    # Use summary_model for summary generation, fallback to current_model if available
                    summary_model = self.summary_model
                    if summary_model is None:
                        try:
                            summary_model = state.current_model
                        except NameError:
                            summary_model = None
                    if add_summary and summary_model:
                        if is_tabular_content:
                            # For CSV/Excel files, auto-summary is rarely meaningful.
                            # Extract column headers and first data row from the markdown table,
                            # then optionally ask the user for context to produce a useful summary.
                            table_header_line = ""
                            table_first_row = ""
                            _all_lines = content_to_chunk.splitlines()
                            for _j, _line in enumerate(_all_lines):
                                if _line.startswith('|') and _j + 1 < len(_all_lines):
                                    _next = _all_lines[_j + 1]
                                    if re.match(r'^\|\s*-{3,}', _next):
                                        table_header_line = _line
                                        if _j + 2 < len(_all_lines) and _all_lines[_j + 2].startswith('|'):
                                            table_first_row = _all_lines[_j + 2]
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

                            if user_context:
                                # Build an enriched prompt combining user context with column/row info
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
                                    document_summary = f"[Document Summary: {summary_response.strip()}]\n\n"
                                    if self.verbose:
                                        on_print(f"Summary generated: {summary_response.strip()}", Fore.GREEN)
                                except Exception as e:
                                    if self.verbose:
                                        on_print(f"Failed to generate summary: {e}", Fore.YELLOW)
                                    document_summary = None
                            else:
                                if self.verbose:
                                    on_print(f"Skipping summary for tabular document {document_id} (no context provided)", Fore.WHITE + Style.DIM)
                        else:
                            if self.verbose:
                                on_print(f"Generating summary for document {document_id} using model: {summary_model}", Fore.WHITE + Style.DIM)
                            summary_prompt = f"""Provide a brief summary (2-5 sentences) of the following document. Focus on the main topic and key points:

{content_to_chunk[:2000]}"""  # Limit to first 2000 chars for summary generation
                            try:
                                ollama_options = {}
                                if num_ctx:
                                    ollama_options["num_ctx"] = num_ctx
                                summary_response = self._ask_fn(
                                    "You are a helpful assistant that creates concise document summaries.",
                                    summary_prompt,
                                    summary_model,
                                    temperature=0.3,
                                    no_bot_prompt=True,
                                    stream_active=False,
                                    num_ctx=num_ctx
                                )
                                document_summary = f"[Document Summary: {summary_response.strip()}]\n\n"
                                if self.verbose:
                                    on_print(f"Summary generated: {summary_response.strip()}", Fore.GREEN)
                            except Exception as e:
                                if self.verbose:
                                    on_print(f"Failed to generate summary: {e}", Fore.YELLOW)
                                document_summary = None
                    
                    for i, chunk in enumerate(chunks):
                        chunk_id = f"{document_id}_{i}"

                        # Check if skipping existing chunks and if the chunk ID exists
                        if skip_existing:
                            existing_chunk = self.collection.get(ids=[chunk_id])
                            if existing_chunk and len(existing_chunk.get('ids', [])) > 0:
                                if self.verbose:
                                    on_print(f"Skipping existing chunk: {chunk_id}", Fore.WHITE + Style.DIM)
                                continue
                        
                        # Prepend document summary to chunk if available
                        chunk_with_summary = chunk
                        if document_summary:
                            chunk_with_summary = document_summary + chunk
                        
                        # Embed the chunk content (from extracted text) with summary prepended
                        embedding = None
                        if self.model:
                            ollama_options = {}
                            if num_ctx:
                                ollama_options["num_ctx"] = num_ctx
                                
                            if self.verbose:
                                embedding_info = f"using extracted text" if extract_start and extract_end else "using full content"
                                summary_info = " with summary" if document_summary else ""
                                on_print(f"Generating embedding for chunk {chunk_id} using {self.model} ({embedding_info}{summary_info})", Fore.WHITE + Style.DIM)
                            # Prepare a potentially truncated string for the embedding call so we don't exceed
                            # the model/context window and risk freezing the Ollama server. The full chunk_with_summary
                            # remains unchanged for storage in ChromaDB.
                            embedding_prompt = self._prepare_text_for_embedding(chunk_with_summary, num_ctx=num_ctx)
                            response = ollama.embeddings(
                                prompt=embedding_prompt,
                                model=self.model,
                                options=ollama_options
                            )
                            embedding = response["embedding"]
                        
                        # Store the chunk with summary prepended
                        chunk_metadata = file_metadata.copy()
                        chunk_metadata['chunk_index'] = i
                        if document_summary:
                            chunk_metadata['has_summary'] = True
                        if store_full_docs:
                            chunk_metadata['store_full_docs'] = True
                        
                        # Determine what to store as the document text:
                        # - If store_full_docs is enabled, store the full original document content
                        #   so that retrieved results contain the complete document.
                        # - Otherwise, store the chunk (with summary prepended if available).
                        # In both cases, the embedding is computed from the chunk with summary.
                        stored_document = content if store_full_docs else chunk_with_summary
                        
                        # Upsert the chunk with summary and embedding
                        if embedding:
                            self.collection.upsert(
                                documents=[stored_document],
                                metadatas=[chunk_metadata],
                                ids=[chunk_id],
                                embeddings=[embedding]  # Embedding computed from chunk with summary
                            )
                        else:
                            self.collection.upsert(
                                documents=[stored_document],
                                metadatas=[chunk_metadata],
                                ids=[chunk_id]
                            )
                    
                else:
                    # Embed the extracted content but store the whole document
                    embedding = None
                    if self.model:
                        ollama_options = {}
                        if num_ctx:
                            ollama_options["num_ctx"] = num_ctx
                            
                        if self.verbose:
                            embedding_info = f"using extracted text" if extract_start and extract_end else "using full content"
                            on_print(f"Generating embedding for document {document_id} using {self.model} ({embedding_info})", Fore.WHITE + Style.DIM)

                        # Use extracted content for embedding computation. Truncate input to embedding API if needed
                        # while keeping the full document content unchanged for storage.
                        embedding_prompt = self._prepare_text_for_embedding(embedding_content, num_ctx=num_ctx)
                        response = ollama.embeddings(
                            prompt=embedding_prompt,
                            model=self.model,
                            options=ollama_options
                        )
                        embedding = response["embedding"]

                    # Store the full document content but use embedding from extracted text
                    if embedding:
                        self.collection.upsert(
                            documents=[content],  # Store full document content
                            metadatas=[file_metadata],
                            ids=[document_id],
                            embeddings=[embedding]  # Embedding computed from extracted text
                        )
                    else:
                        self.collection.upsert(
                            documents=[content],  # Store full document content
                            metadatas=[file_metadata],
                            ids=[document_id]
                        )
            except KeyboardInterrupt:
                break
            except Exception as e: # Catch other potential errors during processing
                on_print(f"Error processing file {file_path}: {e}", Fore.RED)
                continue # Continue to the next file
