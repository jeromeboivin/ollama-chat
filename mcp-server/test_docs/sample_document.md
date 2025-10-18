# MCP Server Test Document

## Introduction

This is a sample document for testing the RAG (Retrieval-Augmented Generation) functionality of the Ollama Chat MCP Server.

## Key Features

The MCP Server includes the following key features:

1. **Web Search** - Comprehensive web search using DuckDuckGo
2. **Document Indexing** - Index local documents into ChromaDB collections
3. **Semantic Search** - Query indexed documents with AI-powered synthesis
4. **Multi-Provider Support** - Works with Azure OpenAI, OpenAI, and Ollama

## Technical Details

### Vector Database

The MCP server uses ChromaDB as its vector database. ChromaDB provides:
- Fast semantic search capabilities
- Automatic persistence to disk
- Support for multiple collections
- Efficient embedding storage

### Embeddings Models

Default embeddings model: `nomic-embed-text`

Other supported models:
- `mxbai-embed-large` - Higher accuracy (1024 dimensions)
- `all-minilm` - Faster performance (384 dimensions)

**Important**: Once you choose an embeddings model for a collection, you cannot change it without recreating the collection.

## Use Cases

### Personal Knowledge Management
Index your personal notes, documents, and research materials for quick retrieval.

### Project Documentation
Keep project documentation searchable and accessible through AI-powered queries.

### Research Assistant
Index research papers and extract relevant information using semantic search.

## Performance

The MCP server is optimized for performance:
- Automatic plugin disabling for built-in tools (20-50% faster startup)
- Smart chunking for optimal retrieval
- Query expansion for better semantic matching
- Configurable result filtering with distance thresholds

## Conclusion

The RAG tools in the Ollama Chat MCP Server provide a powerful way to work with local documents through MCP clients like Claude Desktop.
