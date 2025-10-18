# Ollama Chat MCP Server

A Model Context Protocol (MCP) server that exposes ollama-chat functionality including web search and RAG (Retrieval-Augmented Generation) capabilities through MCP.

## Features

- **Web Search**: Perform comprehensive web searches using DuckDuckGo, crawl results, and synthesize information from multiple sources
- **RAG (Retrieval-Augmented Generation)**: Index and query local documents with semantic search
  - Index documents from folders into ChromaDB collections
  - Query indexed documents with AI-powered synthesis
  - Support for PDF, Word, text, markdown, and more
- **Chat**: Direct interaction with AI models for general queries
- **Multiple AI Providers**: Supports Azure OpenAI, OpenAI, and Ollama with automatic provider detection
- Built on the Model Context Protocol (MCP) standard
- Easy integration with MCP clients like Claude Desktop

## Prerequisites

- Node.js (v18 or higher)
- Python 3.x
- At least one of the following:
  - **Ollama** running locally (default)
  - **OpenAI API** key (set `OPENAI_API_KEY` environment variable)
  - **Azure OpenAI** credentials (set `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT`)
- ollama-chat dependencies installed (see main README)

**Note**: ChromaDB is included automatically! The MCP server uses a local ChromaDB database that will be created automatically in the `mcp_chroma_db` folder. No need to run a separate ChromaDB server.

## AI Provider Configuration

The MCP server supports three AI providers with automatic detection and extensive configuration options.

**📖 For detailed configuration options, see [CONFIGURATION.md](CONFIGURATION.md)**

### Quick Start

The server automatically selects a provider in this priority order:

1. **Azure OpenAI** - If all Azure environment variables are set
2. **OpenAI** - If `OPENAI_API_KEY` is set
3. **Ollama** - Default fallback (local models)

### Supported Providers

#### 1. Azure OpenAI (Highest Priority)

Set these environment variables:
```bash
export AZURE_OPENAI_API_KEY="your-api-key"
export AZURE_OPENAI_ENDPOINT="https://your-resource.openai.azure.com/"
export AZURE_OPENAI_DEPLOYMENT="your-deployment-name"
```

Windows PowerShell:
```powershell
$env:AZURE_OPENAI_API_KEY="your-api-key"
$env:AZURE_OPENAI_ENDPOINT="https://your-resource.openai.azure.com/"
$env:AZURE_OPENAI_DEPLOYMENT="your-deployment-name"
```

#### 2. OpenAI

Set the API key:
```bash
export OPENAI_API_KEY="sk-your-api-key"
```

Windows PowerShell:
```powershell
$env:OPENAI_API_KEY="sk-your-api-key"
```

If `OPENAI_API_KEY` is not set, the server will fall back to local OpenAI-compatible API at `http://127.0.0.1:8080`.

#### 3. Ollama (Default)

No environment variables needed. Just ensure Ollama is running locally.

### Enforcing a Specific Provider

You can override the automatic detection by setting the `MCP_PROVIDER` environment variable:

```bash
# Force Azure OpenAI (will error if credentials not available)
export MCP_PROVIDER="azure"

# Force OpenAI
export MCP_PROVIDER="openai"

# Force Ollama
export MCP_PROVIDER="ollama"

# Auto-detect (default)
export MCP_PROVIDER="auto"
```

Windows PowerShell:
```powershell
$env:MCP_PROVIDER="azure"  # or "openai", "ollama", "auto"
```

### Advanced Configuration

The MCP server supports additional configuration options:

- **`MCP_AZURE_DEPLOYMENT`** - Azure OpenAI deployment name (overrides `AZURE_OPENAI_DEPLOYMENT`)
- **`MCP_OLLAMA_MODEL`** - Default Ollama model to use (e.g., `qwen3:4b`)
- **`MCP_OPENAI_MODEL`** - Default OpenAI model to use (e.g., `gpt-4`)
- **`MCP_EMBEDDINGS_MODEL`** - Ollama embeddings model for vector search (e.g., `nomic-embed-text`)
- **`MCP_ALLOWED_TOOLS`** - Comma-separated list of allowed tools (restricts available tools)

**📖 See [CONFIGURATION.md](CONFIGURATION.md) for detailed examples and explanations.**

### Claude Desktop Configuration Examples

#### Basic Configuration (Auto-detect Provider)
```json
{
  "mcpServers": {
    "ollama-chat": {
      "command": "node",
      "args": ["c:\\dev\\perso\\ollama-chat\\mcp-server\\index.js"]
    }
  }
}
```

#### With Ollama Model Configuration
```json
{
  "mcpServers": {
    "ollama-chat": {
      "command": "node",
      "args": ["c:\\dev\\perso\\ollama-chat\\mcp-server\\index.js"],
      "env": {
        "MCP_OLLAMA_MODEL": "qwen3:4b",
        "MCP_EMBEDDINGS_MODEL": "nomic-embed-text"
      }
    }
  }
}
```
{
#### With Ollama Model Configuration
```json
{
  "mcpServers": {
    "ollama-chat": {
      "command": "node",
      "args": ["c:\\dev\\perso\\ollama-chat\\mcp-server\\index.js"],
      "env": {
        "MCP_OLLAMA_MODEL": "qwen3:4b",
        "MCP_EMBEDDINGS_MODEL": "nomic-embed-text"
      }
    }
  }
}
```

#### Azure OpenAI Configuration
```json
{
  "mcpServers": {
    "ollama-chat": {
      "command": "node",
      "args": ["c:\\dev\\perso\\ollama-chat\\mcp-server\\index.js"],
      "env": {
        "MCP_PROVIDER": "azure",
        "AZURE_OPENAI_API_KEY": "your-api-key",
        "AZURE_OPENAI_ENDPOINT": "https://your-resource.openai.azure.com/",
        "MCP_AZURE_DEPLOYMENT": "gpt-4"
      }
    }
  }
}
```

**📖 More examples in [CONFIGURATION.md](CONFIGURATION.md)**

## Installation

1. Navigate to the mcp-server directory:
```bash
cd mcp-server
```

2. Install dependencies:
```bash
npm install
```

## How ChromaDB Works

The MCP server automatically uses a **local ChromaDB database** stored in the `mcp_chroma_db` folder (created automatically on first use). This means:

✅ **No separate ChromaDB server needed**  
✅ **Automatic database creation**  
✅ **Persistent storage** - search results are cached between sessions  
✅ **No Docker required**

The web_search tool will:
1. Search the web using DuckDuckGo
2. Crawl and extract content from results
3. Store the content in the local ChromaDB database
4. Use vector search to find relevant information
5. Synthesize a comprehensive answer from multiple sources

## Usage

### Running the Server

```bash
npm start
```

For development with auto-reload:
```bash
npm run dev
```

For help and configuration options:
```bash
npm run help
# or
node index.js --help
```

### Testing the Server

To test the server without an MCP client:
```bash
npm test
```

This will run automated tests for both the web_search and chat tools.

**Note**: 
- The `chat` test should work immediately if you have at least one AI provider configured
- The `web_search` test will now work automatically using the local ChromaDB database!

### Available Tools

#### 1. list_available_tools

List all available tools from ollama_chat.py, including both built-in tools and plugin tools.

**Parameters:** None

**Example:**
```json
{}
```

This tool shows you the complete catalog of tools available in ollama_chat.py, including:
- Built-in tools (web search, file operations, etc.)
- Plugin tools (if you have custom plugins)

Use this to discover what tools you can restrict using `MCP_ALLOWED_TOOLS`.

#### 2. web_search

#### 2. web_search

Perform a comprehensive web search similar to Perplexity.

**Parameters:**
- `query` (required): The search query
- `n_results` (optional): Number of results to analyze (default: 5)
- `region` (optional): Region code (e.g., 'wt-wt', 'us-en', 'fr-fr')
- `model` (optional): Model to use (overrides configured model)
- `temperature` (optional): Temperature for responses (0.0-1.0, default: 0.1)

**Example:**
```json
{
  "query": "What are the latest developments in AI?",
  "n_results": 5,
  "region": "us-en"
}
```

#### 3. chat

#### 3. chat

Have a conversation with the AI assistant.

**Parameters:**
- `message` (required): Your message or question
- `model` (optional): Model to use (overrides configured model)
- `temperature` (optional): Temperature for responses (0.0-1.0, default: 0.7)
- `system_prompt` (optional): Custom system prompt

**Example:**
```json
{
  "message": "Explain quantum computing in simple terms",
  "temperature": 0.5
}
```

#### 4. index_documents

Index documents from a folder into a ChromaDB collection for RAG.

**Parameters:**
- `folder_path` (required): Path to folder containing documents
- `collection` (required): Name of ChromaDB collection
- `chunk_documents` (optional): Enable chunking (default: true)
- `skip_existing` (optional): Skip already indexed docs (default: true)
- `extract_start` (optional): Start marker for text extraction
- `extract_end` (optional): End marker for text extraction
- `split_paragraphs` (optional): Split markdown into paragraphs (default: false)
- `add_summary` (optional): Generate AI summaries (default: true)
- `model` (optional): Model to use for summaries

**Example:**
```json
{
  "folder_path": "C:/Documents/MyProject",
  "collection": "project_docs",
  "chunk_documents": true,
  "add_summary": true
}
```

**Supported Formats:** PDF, Word (.docx, .doc), Text (.txt), Markdown (.md), HTML, and more.

**See [RAG_TOOLS.md](RAG_TOOLS.md) for complete documentation.**

#### 5. query_documents

Query indexed documents using semantic search with AI synthesis.

**Parameters:**
- `query` (required): The question or search query
- `collection` (required): Name of ChromaDB collection to query
- `n_results` (optional): Number of results (default: 8)
- `distance_threshold` (optional): Distance threshold for filtering (default: 0.0)
- `expand_query` (optional): Enable query expansion (default: true)
- `synthesize` (optional): Generate AI synthesis (default: true)
- `model` (optional): Model to use for synthesis
- `temperature` (optional): Temperature for responses (0.0-1.0, default: 0.1)

**Example:**
```json
{
  "query": "What are the main features discussed?",
  "collection": "project_docs",
  "n_results": 8,
  "synthesize": true
}
```

**See [RAG_TOOLS.md](RAG_TOOLS.md) for complete documentation and use cases.**

## How It Works

1. The MCP server receives tool calls from MCP clients
2. The server determines which AI provider to use:
   - Auto-detects based on environment variables (Azure OpenAI → OpenAI → Ollama)
   - Or uses the provider specified in `MCP_PROVIDER` environment variable
3. For web searches, it:
   - Calls the ollama-chat Python script with the `/web` command
   - The script searches DuckDuckGo for relevant URLs
   - Crawls and extracts content from top results
   - Indexes content in the local ChromaDB vector database
   - Synthesizes information using the selected AI provider
4. Returns the comprehensive answer to the client

## Architecture

```
MCP Client (e.g., Claude Desktop)
    ↓
MCP Server (Node.js) - Provider Detection
    ↓
ollama_chat.py (Python)
    ↓
┌─────────────┬──────────────┬─────────────────────────────┐
│  DuckDuckGo │ Web Crawler  │   AI Provider:              │
│   Search    │   & Vector   │   - Azure OpenAI            │
│             │   Database   │   - OpenAI                  │
│             │  (ChromaDB)  │   - Ollama (local models)   │
└─────────────┴──────────────┴─────────────────────────────┘
```

## Troubleshooting

### Provider Detection Issues

**Check which provider is being used:**
The server logs provider information to stderr when starting. Check Claude Desktop logs or run in test mode:
```bash
npm test
```

**Azure OpenAI not being detected:**
- Verify all three environment variables are set: `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT`
- Check the values don't have trailing spaces or quotes
- Restart Claude Desktop after setting environment variables

**OpenAI not being detected:**
- Verify `OPENAI_API_KEY` is set correctly
- Make sure the key starts with `sk-`
- Restart Claude Desktop after setting the environment variable

**Force a specific provider:**
Set `MCP_PROVIDER` to `azure`, `openai`, or `ollama` to bypass auto-detection

### Server won't start
- Ensure Node.js is installed: `node --version`
- Check that all dependencies are installed: `npm install`
- Verify the path to `ollama_chat.py` is correct in `index.js`

### Python script errors
- Make sure Python is in your PATH
- Verify ollama-chat dependencies are installed (including chromadb)
- If using Ollama, check that it's running locally
- If using OpenAI/Azure, verify API credentials are correct

### Web search is slow on first use
- The first web search creates the ChromaDB database and indexes content
- Subsequent searches with similar topics will be faster due to caching
- The database is stored in `mcp_chroma_db` folder

### Clear the ChromaDB cache
If you want to clear the cached web search results:
```bash
# Delete the ChromaDB database folder
rm -rf ../mcp_chroma_db
# Windows PowerShell:
Remove-Item -Recurse -Force ..\mcp_chroma_db
```

## Development

To modify the server:

1. Edit `index.js` to add new tools or modify existing ones
2. Test with `npm run dev` for auto-reload
3. Restart Claude Desktop to reload the MCP configuration

## Documentation

- **[RAG_TOOLS.md](RAG_TOOLS.md)** - Complete guide to RAG (document indexing and querying)
- **[CONFIGURATION.md](CONFIGURATION.md)** - Detailed configuration options
- **[QUICKSTART.md](QUICKSTART.md)** - Quick start guide

## License

MIT
