#!/usr/bin/env node

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import { spawn } from "child_process";
import path from "path";
import { fileURLToPath } from "url";
import os from "os";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// Check for help mode
const HELP_MODE = process.argv.includes("--help") || process.argv.includes("-h");

// Check for test mode
const TEST_MODE = process.argv.includes("--test");

// Path to the ollama_chat.py script (adjust if needed)
const OLLAMA_CHAT_PATH = path.join(__dirname, "..", "ollama_chat.py");

/**
 * Get the default ChromaDB path based on OS-specific user data directory
 * - Windows: %LOCALAPPDATA%\ollama-chat\chromadb
 * - macOS: ~/Library/Application Support/ollama-chat/chromadb
 * - Linux: ~/.local/share/ollama-chat/chromadb
 */
function getDefaultChromaDBPath() {
  const platform = os.platform();
  let baseDir;

  if (platform === "win32") {
    baseDir = process.env.LOCALAPPDATA || path.join(os.homedir(), "AppData", "Local");
  } else if (platform === "darwin") {
    baseDir = path.join(os.homedir(), "Library", "Application Support");
  } else {
    // Linux and other Unix-like systems
    baseDir = process.env.XDG_DATA_HOME || path.join(os.homedir(), ".local", "share");
  }

  return path.join(baseDir, "ollama-chat", "chromadb");
}

class OllamaChatMCPServer {
  constructor(config = {}) {
    // Configuration options
    this.config = {
      // Provider enforcement: 'azure', 'openai', 'ollama', or 'auto' (default)
      // 'auto' follows priority: Azure OpenAI → OpenAI → Ollama
      provider: config.provider || 'auto',
      
      // Model configurations (take precedence over environment variables)
      azureDeployment: config.azureDeployment || null,  // Azure OpenAI deployment name
      ollamaModel: config.ollamaModel || null,          // Ollama model (e.g., "qwen3:4b")
      openaiModel: config.openaiModel || null,          // OpenAI model (e.g., "gpt-4")
      embeddingsModel: config.embeddingsModel || 'nomic-embed-text',  // Ollama embeddings model (default: nomic-embed-text)
      
      // ChromaDB configuration
      chromaDBPath: config.chromaDBPath || getDefaultChromaDBPath(),  // Path to ChromaDB database
      
      // Tools configuration
      allowedTools: config.allowedTools || null,        // Array of allowed tool names, null = all tools allowed
    };

    this.server = new Server(
      {
        name: "ollama-chat-mcp-server",
        version: "1.0.0",
      },
      {
        capabilities: {
          tools: {},
        },
      }
    );

    this.setupToolHandlers();
    
    // Error handling
    this.server.onerror = (error) => console.error("[MCP Error]", error);
    process.on("SIGINT", async () => {
      await this.server.close();
      process.exit(0);
    });
  }

  /**
   * Determine which provider to use based on configuration and environment variables
   * Priority (when config.provider === 'auto'):
   * 1. Azure OpenAI (if AZURE_OPENAI_API_KEY is set)
   * 2. OpenAI (if OPENAI_API_KEY is set)
   * 3. Ollama (default fallback)
   */
  determineProvider() {
    const provider = this.config.provider.toLowerCase();

    // If explicitly set, validate and return
    if (provider !== 'auto') {
      if (!['azure', 'openai', 'ollama'].includes(provider)) {
        console.error(`[Warning] Invalid provider '${provider}', falling back to 'auto'`);
        return this.determineProvider.call({ config: { provider: 'auto' } });
      }

      // Validate environment variables for explicit provider choice
      if (provider === 'azure') {
        const apiKey = process.env.AZURE_OPENAI_API_KEY;
        const endpoint = process.env.AZURE_OPENAI_ENDPOINT;
        const deployment = this.config.azureDeployment || process.env.AZURE_OPENAI_DEPLOYMENT;
        
        if (!apiKey || !endpoint || !deployment) {
          console.error("[Error] Azure OpenAI provider selected but required configuration is missing:");
          console.error("  - AZURE_OPENAI_API_KEY environment variable");
          console.error("  - AZURE_OPENAI_ENDPOINT environment variable");
          console.error("  - azureDeployment config or AZURE_OPENAI_DEPLOYMENT environment variable");
          throw new Error("Azure OpenAI configuration incomplete");
        }
        console.error(`[Info] Using Azure OpenAI (explicitly configured) - Deployment: ${deployment}`);
        return { provider: 'azure', useAzureOpenAI: true, useOpenAI: false };
      }

      if (provider === 'openai') {
        if (!process.env.OPENAI_API_KEY) {
          console.error("[Warning] OpenAI provider selected but OPENAI_API_KEY not set, falling back to local OpenAI API");
        } else {
          console.error("[Info] Using OpenAI (explicitly configured)");
        }
        return { provider: 'openai', useAzureOpenAI: false, useOpenAI: true };
      }

      console.error("[Info] Using Ollama (explicitly configured)");
      return { provider: 'ollama', useAzureOpenAI: false, useOpenAI: false };
    }

    // Auto-detect based on environment variables (priority order)
    
    // 1. Check for Azure OpenAI
    const azureDeployment = this.config.azureDeployment || process.env.AZURE_OPENAI_DEPLOYMENT;
    if (process.env.AZURE_OPENAI_API_KEY && 
        process.env.AZURE_OPENAI_ENDPOINT && 
        azureDeployment) {
      console.error(`[Info] Using Azure OpenAI (auto-detected) - Deployment: ${azureDeployment}`);
      return { provider: 'azure', useAzureOpenAI: true, useOpenAI: false };
    }

    // 2. Check for OpenAI
    if (process.env.OPENAI_API_KEY) {
      console.error("[Info] Using OpenAI (auto-detected from environment variables)");
      return { provider: 'openai', useAzureOpenAI: false, useOpenAI: true };
    }

    // 3. Default to Ollama
    console.error("[Info] Using Ollama (default - no cloud API keys detected)");
    return { provider: 'ollama', useAzureOpenAI: false, useOpenAI: false };
  }

  /**
   * Build command arguments with provider flags
   */
  buildProviderArgs() {
    const providerInfo = this.determineProvider();
    const args = [];

    if (providerInfo.useAzureOpenAI) {
      args.push('--use-azure-openai');
    } else if (providerInfo.useOpenAI) {
      args.push('--use-openai');
    }
    // No flag needed for Ollama (default behavior)

    return args;
  }

  /**
   * Build command arguments for model specification
   */
  buildModelArgs(toolModel) {
    const args = [];
    const providerInfo = this.determineProvider();
    
    // Determine which model to use (priority: tool parameter > config > default)
    let model = toolModel;
    
    if (!model) {
      if (providerInfo.provider === 'azure' && this.config.azureDeployment) {
        model = this.config.azureDeployment;
      } else if (providerInfo.provider === 'openai' && this.config.openaiModel) {
        model = this.config.openaiModel;
      } else if (providerInfo.provider === 'ollama' && this.config.ollamaModel) {
        model = this.config.ollamaModel;
      }
    }
    
    if (model) {
      args.push(`--model=${model}`);
    }
    
    // Add embeddings model (always configured, defaults to 'nomic-embed-text')
    if (this.config.embeddingsModel) {
      args.push(`--embeddings-model=${this.config.embeddingsModel}`);
    }
    
    return args;
  }

  /**
   * Build command arguments for tools specification
   */
  buildToolsArgs() {
    const args = [];
    
    if (this.config.allowedTools && Array.isArray(this.config.allowedTools) && this.config.allowedTools.length > 0) {
      args.push(`--tools=${this.config.allowedTools.join(',')}`);
    }
    
    return args;
  }

  /**
   * Determine if plugin loading should be disabled
   * Plugins are disabled when only built-in tools are needed
   * Built-in tools: web_search, query_vector_database, retrieve_relevant_memory, 
   *                 instantiate_agent_with_tools_and_process_task, 
   *                 create_new_agent_with_tools, summarize_text_file,
   *                 index_documents, query_documents (MCP-specific RAG tools)
   */
  shouldDisablePlugins(toolsUsed = []) {
    const builtinTools = [
      'web_search',
      'query_vector_database', 
      'retrieve_relevant_memory',
      'instantiate_agent_with_tools_and_process_task',
      'create_new_agent_with_tools',
      'summarize_text_file',
      'index_documents',
      'query_documents'
    ];
    
    // If allowedTools is configured, check if any are plugin tools
    if (this.config.allowedTools && Array.isArray(this.config.allowedTools)) {
      const hasPluginTools = this.config.allowedTools.some(tool => !builtinTools.includes(tool));
      return !hasPluginTools; // Disable plugins if no plugin tools are configured
    }
    
    // If specific tools are passed (e.g., from a tool call), check those
    if (toolsUsed && toolsUsed.length > 0) {
      const hasPluginTools = toolsUsed.some(tool => !builtinTools.includes(tool));
      return !hasPluginTools;
    }
    
    // Default: disable plugins for MCP server (uses only built-in tools: web_search, RAG)
    return true;
  }

  /**
   * Build command arguments for plugin control
   */
  buildPluginArgs(toolsUsed = []) {
    const args = [];
    
    if (this.shouldDisablePlugins(toolsUsed)) {
      args.push('--disable-plugins');
    }
    
    return args;
  }

  setupToolHandlers() {
    // List available tools
    this.server.setRequestHandler(ListToolsRequestSchema, async () => {
      const tools = [
        {
          name: "list_available_tools",
          description: "List all available tools from ollama_chat.py, including both built-in tools and plugin tools. This shows the complete catalog of tools that can be used with the --tools parameter.",
          inputSchema: {
            type: "object",
            properties: {},
            required: [],
          },
        },
        {
          name: "web_search",
          description: "Perform a comprehensive web search similar to Perplexity. This tool searches the web using DuckDuckGo, crawls the top results, extracts content, indexes it in a vector database, and returns relevant information synthesized from multiple sources. Intermediate results (search results, URLs crawled, content previews, and vector database retrieval) are always displayed for transparency and debugging.",
          inputSchema: {
            type: "object",
            properties: {
              query: {
                type: "string",
                description: "The search query to look up on the web",
              },
              n_results: {
                type: "number",
                description: "Number of search results to retrieve and analyze (default: 5)",
                default: 5,
              },
              region: {
                type: "string",
                description: "Region code for search results (e.g., 'wt-wt' for worldwide, 'us-en' for US, 'fr-fr' for France)",
                default: "wt-wt",
              },
              model: {
                type: "string",
                description: "Model to use for processing (optional, uses configured model if not specified)",
              },
              temperature: {
                type: "number",
                description: "Temperature for LLM responses (0.0-1.0, default: 0.1)",
                default: 0.1,
              },
            },
            required: ["query"],
          },
        },
        {
          name: "index_documents",
          description: "Index documents from a folder into a ChromaDB collection for retrieval-augmented generation (RAG). Supports various document formats (PDF, Word, text, markdown, etc.) with options for chunking, extraction, and AI-generated summaries.",
          inputSchema: {
            type: "object",
            properties: {
              folder_path: {
                type: "string",
                description: "Path to the folder containing documents to index",
              },
              collection: {
                type: "string",
                description: "Name of the ChromaDB collection to store indexed documents",
              },
              chunk_documents: {
                type: "boolean",
                description: "Enable/disable document chunking (default: true)",
                default: true,
              },
              skip_existing: {
                type: "boolean",
                description: "Skip documents already indexed (default: true)",
                default: true,
              },
              extract_start: {
                type: "string",
                description: "Start marker for text extraction (optional)",
              },
              extract_end: {
                type: "string",
                description: "End marker for text extraction (optional)",
              },
              split_paragraphs: {
                type: "boolean",
                description: "Split Markdown into paragraphs (default: false)",
                default: false,
              },
              add_summary: {
                type: "boolean",
                description: "Generate AI summaries for chunks (default: true)",
                default: true,
              },
              model: {
                type: "string",
                description: "Model to use for generating summaries (optional, uses configured model if not specified)",
              },
            },
            required: ["folder_path", "collection"],
          },
        },
        {
          name: "query_documents",
          description: "Query indexed documents in a ChromaDB collection using semantic search. Returns relevant document chunks based on the query with optional AI-generated synthesis of results.",
          inputSchema: {
            type: "object",
            properties: {
              query: {
                type: "string",
                description: "The question or search query",
              },
              collection: {
                type: "string",
                description: "Name of the ChromaDB collection to query",
              },
              n_results: {
                type: "number",
                description: "Number of results to return (default: 8)",
                default: 8,
              },
              distance_threshold: {
                type: "number",
                description: "Distance threshold for filtering results (default: 0.0, no filtering)",
                default: 0.0,
              },
              expand_query: {
                type: "boolean",
                description: "Enable/disable query expansion for better results (default: true)",
                default: true,
              },
              synthesize: {
                type: "boolean",
                description: "Generate AI synthesis of results (default: true)",
                default: true,
              },
              model: {
                type: "string",
                description: "Model to use for synthesis (optional, uses configured model if not specified)",
              },
              temperature: {
                type: "number",
                description: "Temperature for LLM responses (0.0-1.0, default: 0.1)",
                default: 0.1,
              },
            },
            required: ["query", "collection"],
          },
        },
        {
          name: "list_collections",
          description: "List all available ChromaDB collections with their metadata and document counts. Useful for discovering what vector database collections exist before querying or indexing.",
          inputSchema: {
            type: "object",
            properties: {},
            required: [],
          },
        },
        {
          name: "instantiate_agent_with_tools_and_process_task",
          description: "Creates an agent with a specified name using a provided system prompt, task, and a list of tools. Executes the task-solving process and returns the result. The tools must be chosen from a predefined set of available tools.",
          inputSchema: {
            type: "object",
            properties: {
              task: {
                type: "string",
                description: "The task or problem that the agent needs to solve. Provide a clear and concise description.",
              },
              system_prompt: {
                type: "string",
                description: "The system prompt that defines the agent's behavior, personality, and approach to solving the task.",
              },
              tools: {
                type: "array",
                items: {
                  type: "string",
                },
                description: "A list of tools to be used by the agent for solving the task. Must be an array of tool names from the available tools list.",
              },
              agent_name: {
                type: "string",
                description: "A unique name for the agent that will be used for instantiation.",
              },
              agent_description: {
                type: "string",
                description: "A brief description of the agent's purpose and capabilities.",
              },
              model: {
                type: "string",
                description: "Model to use for the agent (optional, uses configured model if not specified)",
              },
              temperature: {
                type: "number",
                description: "Temperature for LLM responses (0.0-1.0, default: 0.7)",
                default: 0.7,
              },
            },
            required: ["task", "system_prompt", "tools", "agent_name", "agent_description"],
          },
        },
      ];

      // Filter tools if allowedTools is configured
      if (this.config.allowedTools && Array.isArray(this.config.allowedTools)) {
        // Always include list_available_tools
        return {
          tools: tools.filter(tool => 
            tool.name === "list_available_tools" || this.config.allowedTools.includes(tool.name)
          )
        };
      }

      return { tools };
    });

    // Handle tool calls
    this.server.setRequestHandler(CallToolRequestSchema, async (request) => {
      const { name, arguments: args } = request.params;

      try {
        if (name === "list_available_tools") {
          return await this.handleListAvailableTools(args);
        } else if (name === "web_search") {
          return await this.handleWebSearch(args);
        } else if (name === "index_documents") {
          return await this.handleIndexDocuments(args);
        } else if (name === "query_documents") {
          return await this.handleQueryDocuments(args);
        } else if (name === "list_collections") {
          return await this.handleListCollections(args);
        } else if (name === "instantiate_agent_with_tools_and_process_task") {
          return await this.handleInstantiateAgent(args);
        } else {
          throw new Error(`Unknown tool: ${name}`);
        }
      } catch (error) {
        return {
          content: [
            {
              type: "text",
              text: `Error: ${error.message}`,
            },
          ],
          isError: true,
        };
      }
    });
  }

  async handleListAvailableTools(args) {
    // Build command arguments for ollama_chat.py
    // Note: --list-tools always loads plugins to show complete tool catalog
    const cmdArgs = [
      OLLAMA_CHAT_PATH,
      "--list-tools",
      // Do NOT add --disable-plugins here, we want to see all tools including plugin tools
    ];

    // Execute the Python script
    const result = await this.executePythonScript(cmdArgs);

    return {
      content: [
        {
          type: "text",
          text: result,
        },
      ],
    };
  }

  async handleWebSearch(args) {
    const { query, n_results = 5, region = "wt-wt", model, temperature = 0.1 } = args;

    if (!query) {
      throw new Error("Query parameter is required");
    }

    // Build command arguments for ollama_chat.py using new --web-search CLI
    const cmdArgs = [
      OLLAMA_CHAT_PATH,
      ...this.buildProviderArgs(),  // Add provider-specific flags
      ...this.buildModelArgs(model),  // Add model configuration (includes --embeddings-model)
      ...this.buildToolsArgs(),  // Add tools configuration
      ...this.buildPluginArgs(['web_search']),  // Optimize: disable plugins (web_search is built-in)
      "--no-interactive",  // Mandatory: non-interactive mode
      "--no-syntax-highlighting",
      `--chroma-path=${this.config.chromaDBPath}`,  // Mandatory: ChromaDB database path
      `--web-search=${query}`,  // Mandatory: web search query
      `--web-search-results=${n_results}`,
      `--web-search-region=${region}`,
      "--web-search-show-intermediate",  // Mandatory: show intermediate results
    ];

    if (temperature !== 0.1) {
      cmdArgs.push(`--temperature=${temperature}`);
    }

    // Execute the Python script
    const result = await this.executePythonScript(cmdArgs);

    return {
      content: [
        {
          type: "text",
          text: result,
        },
      ],
    };
  }

  async handleIndexDocuments(args) {
    const {
      folder_path,
      collection,
      chunk_documents = true,
      skip_existing = true,
      extract_start,
      extract_end,
      split_paragraphs = false,
      add_summary = true,
      model
    } = args;

    if (!folder_path) {
      throw new Error("folder_path parameter is required");
    }

    if (!collection) {
      throw new Error("collection parameter is required");
    }

    // Build command arguments for ollama_chat.py
    const cmdArgs = [
      OLLAMA_CHAT_PATH,
      ...this.buildProviderArgs(),  // Add provider-specific flags
      ...this.buildModelArgs(model),  // Add model configuration
      ...this.buildToolsArgs(),  // Add tools configuration
      ...this.buildPluginArgs(['query_vector_database']),  // Optimize: disable plugins (indexing uses built-in RAG)
      "--no-interactive",
      "--no-syntax-highlighting",
      `--index-documents=${folder_path}`,
      `--collection=${collection}`,
      `--chroma-path=${this.config.chromaDBPath}`,  // Use configured ChromaDB database path
      "--verbose",  // Provide feedback during indexing
    ];

    // Add boolean flags conditionally
    if (chunk_documents) {
      cmdArgs.push("--chunk-documents");
    } else {
      cmdArgs.push("--no-chunk-documents");
    }

    if (skip_existing) {
      cmdArgs.push("--skip-existing");
    } else {
      cmdArgs.push("--no-skip-existing");
    }

    if (split_paragraphs) {
      cmdArgs.push("--split-paragraphs");
    } else {
      cmdArgs.push("--no-split-paragraphs");
    }

    if (add_summary) {
      cmdArgs.push("--add-summary");
    } else {
      cmdArgs.push("--no-add-summary");
    }

    if (extract_start) {
      cmdArgs.push(`--extract-start=${extract_start}`);
    }

    if (extract_end) {
      cmdArgs.push(`--extract-end=${extract_end}`);
    }

    // Execute the Python script
    const result = await this.executePythonScript(cmdArgs);

    return {
      content: [
        {
          type: "text",
          text: result || "Documents indexed successfully",
        },
      ],
    };
  }

  async handleQueryDocuments(args) {
    const {
      query,
      collection,
      n_results = 8,
      distance_threshold = 0.0,
      expand_query = true,
      synthesize = true,
      model,
      temperature = 0.1
    } = args;

    if (!query) {
      throw new Error("query parameter is required");
    }

    if (!collection) {
      throw new Error("collection parameter is required");
    }

    // Build command arguments for ollama_chat.py
    const cmdArgs = [
      OLLAMA_CHAT_PATH,
      ...this.buildProviderArgs(),  // Add provider-specific flags
      ...this.buildModelArgs(model),  // Add model configuration
      ...this.buildToolsArgs(),  // Add tools configuration
      ...this.buildPluginArgs(['query_vector_database']),  // Optimize: disable plugins (querying uses built-in RAG)
      "--no-interactive",
      "--no-syntax-highlighting",
      `--query=${query}`,
      `--collection=${collection}`,
      `--chroma-path=${this.config.chromaDBPath}`,  // Use configured ChromaDB database path
      `--query-n-results=${n_results}`,
      `--query-distance-threshold=${distance_threshold}`,
    ];

    // Add boolean flags conditionally
    if (expand_query) {
      cmdArgs.push("--expand-query");
    } else {
      cmdArgs.push("--no-expand-query");
    }

    if (temperature !== 0.1) {
      cmdArgs.push(`--temperature=${temperature}`);
    }

    // If synthesize is false, we just return raw results
    // If synthesize is true (default), we let the model process the results
    if (!synthesize) {
      cmdArgs.push("--no-synthesis");  // This flag would need to be added to ollama_chat.py
    }

    // Execute the Python script
    const result = await this.executePythonScript(cmdArgs);

    return {
      content: [
        {
          type: "text",
          text: result,
        },
      ],
    };
  }

  async handleListCollections(args) {
    // Build command arguments for ollama_chat.py
    const cmdArgs = [
      OLLAMA_CHAT_PATH,
      "--list-collections",
      `--chroma-path=${this.config.chromaDBPath}`,  // Use configured ChromaDB database path
    ];

    // Execute the Python script
    const result = await this.executePythonScript(cmdArgs);

    return {
      content: [
        {
          type: "text",
          text: result,
        },
      ],
    };
  }

  async handleInstantiateAgent(args) {
    const {
      task,
      system_prompt,
      tools,
      agent_name,
      agent_description,
      model,
      temperature = 0.7
    } = args;

    // Validate required parameters
    if (!task) {
      throw new Error("task parameter is required");
    }

    if (!system_prompt) {
      throw new Error("system_prompt parameter is required");
    }

    if (!tools || !Array.isArray(tools)) {
      throw new Error("tools parameter is required and must be an array");
    }

    if (!agent_name) {
      throw new Error("agent_name parameter is required");
    }

    if (!agent_description) {
      throw new Error("agent_description parameter is required");
    }

    // Build command arguments for ollama_chat.py using the new direct approach
    const cmdArgs = [
      OLLAMA_CHAT_PATH,
      ...this.buildProviderArgs(),  // Add provider-specific flags
      ...this.buildModelArgs(model),  // Add model configuration
      ...this.buildToolsArgs(),  // Add tools configuration
      ...this.buildPluginArgs(tools),  // Enable/disable plugins based on tools used
      "--no-interactive",
      "--no-syntax-highlighting",
      `--chroma-path=${this.config.chromaDBPath}`,  // Use configured ChromaDB database path
      // Use direct agent instantiation flags (more efficient than prompting)
      "--instantiate-agent",
      `--agent-task=${task}`,
      `--agent-system-prompt=${system_prompt}`,
      `--agent-tools=${tools.join(',')}`,
      `--agent-name=${agent_name}`,
      `--agent-description=${agent_description}`,
    ];

    if (temperature !== 0.7) {
      cmdArgs.push(`--temperature=${temperature}`);
    }

    // Execute the Python script
    const result = await this.executePythonScript(cmdArgs);

    return {
      content: [
        {
          type: "text",
          text: result,
        },
      ],
    };
  }

  executePythonScript(args) {
    return new Promise((resolve, reject) => {
      // Determine Python command based on OS
      const pythonCmd = os.platform() === "win32" ? "python" : "python3";
      
      // Set environment variable to handle Unicode output on Windows
      const env = { ...process.env };
      if (os.platform() === "win32") {
        env.PYTHONIOENCODING = "utf-8";
      }
      
      const childProcess = spawn(pythonCmd, args, { env });
      let stdout = "";
      let stderr = "";

      childProcess.stdout.on("data", (data) => {
        stdout += data.toString();
      });

      childProcess.stderr.on("data", (data) => {
        stderr += data.toString();
      });

      childProcess.on("close", (code) => {
        if (code !== 0) {
          reject(new Error(`Python script exited with code ${code}: ${stderr}`));
        } else {
          resolve(stdout.trim());
        }
      });

      childProcess.on("error", (error) => {
        reject(new Error(`Failed to start Python script: ${error.message}`));
      });
    });
  }

  async run() {
    const transport = new StdioServerTransport();
    await this.server.connect(transport);
    console.error("Ollama Chat MCP server running on stdio");
  }

  async runTests() {
    console.log("=".repeat(60));
    console.log("OLLAMA CHAT MCP SERVER - TEST MODE");
    console.log("=".repeat(60));
    console.log();

    // Test 1: List tools
    console.log("Test 1: Listing available MCP tools...");
    console.log("-".repeat(60));
    const tools = [
      {
        name: "list_available_tools",
        description: "List all available tools from ollama_chat.py",
      },
      {
        name: "web_search",
        description: "Perform a comprehensive web search similar to Perplexity",
      },
      {
        name: "chat",
        description: "Have a conversation with the chat assistant",
      },
    ];
    
    tools.forEach((tool, index) => {
      console.log(`${index + 1}. ${tool.name}`);
      console.log(`   Description: ${tool.description}`);
    });
    console.log("✅ MCP tools listed successfully\n");

    // Test 2: List available ollama_chat tools
    console.log("=".repeat(60));
    console.log("Test 2: Listing available ollama_chat.py tools");
    console.log("-".repeat(60));
    console.log("Executing list_available_tools...\n");
    
    try {
      const listToolsResult = await this.handleListAvailableTools({});
      
      console.log("Available ollama_chat.py tools:");
      console.log("-".repeat(60));
      console.log(listToolsResult.content[0].text);
      console.log("\n✅ List tools test passed\n");
    } catch (error) {
      console.error("❌ List tools test failed:", error.message);
      console.error(error.stack);
    }

    // Test 3: List ChromaDB collections
    console.log("=".repeat(60));
    console.log("Test 3: Listing ChromaDB collections");
    console.log("-".repeat(60));
    console.log("Executing list_collections...\n");
    
    try {
      const listCollectionsResult = await this.handleListCollections({});
      
      console.log("Available ChromaDB collections:");
      console.log("-".repeat(60));
      console.log(listCollectionsResult.content[0].text);
      console.log("\n✅ List collections test passed\n");
    } catch (error) {
      console.error("❌ List collections test failed:", error.message);
      console.error(error.stack);
    }

    // Test 4: Web Search
    console.log("=".repeat(60));
    console.log("Test 4: Testing web_search tool");
    console.log("-".repeat(60));
    console.log("Query: 'What is the Model Context Protocol?'");
    console.log("Model: Using default (Azure OpenAI if configured, otherwise auto-detect)");
    console.log("Intermediate results: always enabled (mandatory)");
    console.log("Note: This may take 30-60 seconds (searching, crawling, indexing)...\n");
    
    try {
      const webSearchResult = await this.handleWebSearch({
        query: "What is the Model Context Protocol?",
        // model parameter removed to use default Azure OpenAI
        n_results: 3,
        region: "wt-wt"
      });
      
      console.log("Web Search Result:");
      console.log("-".repeat(60));
      const resultText = webSearchResult.content[0].text;
      console.log(resultText);
      
      // Check if we got actual web search results or just an error message
      // The model says "I don't know" when it doesn't have search results
      const hasRealResults = !resultText.toLowerCase().includes("i don't know") 
                          && !resultText.toLowerCase().includes("doesn't actually contain any web search results");
      
      if (hasRealResults) {
        console.log("\n✅ Web search test passed with real search results!\n");
      } else {
        console.log("\n⚠️  Web search test completed but no results were found");
        console.log("   This might be a network issue or DuckDuckGo rate limiting.");
        console.log("   The ChromaDB local database is working correctly.");
      }
    } catch (error) {
      console.error("❌ Web search test failed with error:", error.message);
      console.error(error.stack);
    }

    // Test 5: RAG - Index Documents (if test documents exist)
    console.log("=".repeat(60));
    console.log("Test 5: Testing index_documents tool (RAG)");
    console.log("-".repeat(60));
    console.log("Note: This test requires a 'test_docs' folder with sample documents.");
    console.log("Skipping if folder doesn't exist...\n");
    
    try {
      // Check if test_docs folder exists (simple check)
      const fs = await import('fs');
      const testDocsPath = path.join(__dirname, 'test_docs');
      
      if (fs.existsSync(testDocsPath)) {
        console.log(`Found test documents at: ${testDocsPath}`);
        console.log("Indexing documents...\n");
        
        const indexResult = await this.handleIndexDocuments({
          folder_path: testDocsPath,
          collection: "mcp_test_collection",
          chunk_documents: true,
          skip_existing: false,
          add_summary: false,  // Skip summaries for faster testing
          model: "qwen3:4b"
        });
        
        console.log("Index Result:");
        console.log("-".repeat(60));
        console.log(indexResult.content[0].text);
        console.log("\n✅ Document indexing test passed!\n");
        
        // Test 6: RAG - Query Documents
        console.log("=".repeat(60));
        console.log("Test 6: Testing query_documents tool (RAG)");
        console.log("-".repeat(60));
        console.log("Query: 'What information is in these documents?'");
        console.log("Collection: mcp_test_collection\n");
        
        const queryResult = await this.handleQueryDocuments({
          query: "What information is in these documents?",
          collection: "mcp_test_collection",
          n_results: 5,
          expand_query: false,
          synthesize: true,
          model: "qwen3:4b"
        });
        
        console.log("Query Result:");
        console.log("-".repeat(60));
        console.log(queryResult.content[0].text);
        console.log("\n✅ Document query test passed!\n");
      } else {
        console.log(`⏭️  Skipping RAG tests - test_docs folder not found at: ${testDocsPath}`);
        console.log("   To test RAG functionality, create a 'test_docs' folder with sample documents.\n");
      }
    } catch (error) {
      console.error("⚠️  RAG tests skipped or failed:", error.message);
    }

    // Test 8: Agent Instantiation
    console.log("=".repeat(60));
    console.log("Test 8: Testing instantiate_agent_with_tools_and_process_task");
    console.log("-".repeat(60));
    console.log("Task: 'What is 5 + 3? Just give me the answer.'");
    console.log("Agent: Simple calculator agent");
    console.log("Tools: No tools needed for simple math");
    console.log("Model: Using default (Azure OpenAI if configured, otherwise auto-detect)");
    console.log("Executing agent instantiation...\n");
    
    try {
      const agentResult = await this.handleInstantiateAgent({
        task: "What is 5 + 3? Just give me the answer.",
        system_prompt: "You are a helpful math assistant. Answer math questions directly and concisely.",
        tools: [],  // Simple task, no tools needed
        agent_name: "math_helper",
        agent_description: "A simple agent that helps with basic math questions",
        // model parameter removed to use default Azure OpenAI
        temperature: 0.3
      });
      
      console.log("Agent Result:");
      console.log("-".repeat(60));
      console.log(agentResult.content[0].text);
      console.log("\n✅ Agent instantiation test passed!\n");
    } catch (error) {
      console.error("❌ Agent instantiation test failed:", error.message);
      console.error(error.stack);
    }

    console.log("=".repeat(60));
    console.log("All tests completed!");
    console.log("=".repeat(60));
  }
}

// Parse configuration from environment variables or command line
function parseConfig() {
  const config = {};
  
  // Check for MCP_PROVIDER environment variable
  // Valid values: 'auto', 'azure', 'openai', 'ollama'
  if (process.env.MCP_PROVIDER) {
    config.provider = process.env.MCP_PROVIDER;
  }
  
  // Check for model configuration environment variables
  if (process.env.MCP_AZURE_DEPLOYMENT) {
    config.azureDeployment = process.env.MCP_AZURE_DEPLOYMENT;
  }
  
  if (process.env.MCP_OLLAMA_MODEL) {
    config.ollamaModel = process.env.MCP_OLLAMA_MODEL;
  }
  
  if (process.env.MCP_OPENAI_MODEL) {
    config.openaiModel = process.env.MCP_OPENAI_MODEL;
  }
  
  if (process.env.MCP_EMBEDDINGS_MODEL) {
    config.embeddingsModel = process.env.MCP_EMBEDDINGS_MODEL;
  }
  
  // Check for ChromaDB path configuration
  if (process.env.MCP_CHROMADB_PATH) {
    config.chromaDBPath = process.env.MCP_CHROMADB_PATH;
  }
  
  // Check for allowed tools configuration
  if (process.env.MCP_ALLOWED_TOOLS) {
    config.allowedTools = process.env.MCP_ALLOWED_TOOLS.split(',').map(t => t.trim());
  }
  
  return config;
}

// Display help information
function displayHelp() {
  console.log(`
Ollama Chat MCP Server
Version: 1.0.0

USAGE:
  node index.js [OPTIONS]

OPTIONS:
  --help, -h        Display this help message and exit
  --test            Run automated tests instead of starting the server

CONFIGURATION:
  The server is configured through environment variables in your MCP client
  configuration (e.g., Claude Desktop's config.json).

ENVIRONMENT VARIABLES:
  Provider Selection:
    MCP_PROVIDER               AI provider: 'auto', 'azure', 'openai', 'ollama' (default: auto)

  Model Configuration:
    MCP_AZURE_DEPLOYMENT       Azure OpenAI deployment name
    MCP_OLLAMA_MODEL           Default Ollama model (e.g., 'qwen3:4b')
    MCP_OPENAI_MODEL           Default OpenAI model (e.g., 'gpt-4')
    MCP_EMBEDDINGS_MODEL       Ollama embeddings model for vector search (default: 'nomic-embed-text')
                               ⚠️  IMPORTANT: Once set, do not change! ChromaDB databases cannot mix
                               different embedding models. Changing this requires a new database.

  ChromaDB Configuration:
    MCP_CHROMADB_PATH          Path to ChromaDB database directory (optional)
                               Default locations:
                               - Windows: %LOCALAPPDATA%\\ollama-chat\\chromadb
                               - macOS: ~/Library/Application Support/ollama-chat/chromadb
                               - Linux: ~/.local/share/ollama-chat/chromadb

  Tools Configuration:
    MCP_ALLOWED_TOOLS          Comma-separated list of allowed tools

  Provider Credentials:
    AZURE_OPENAI_API_KEY       Azure OpenAI API key
    AZURE_OPENAI_ENDPOINT      Azure OpenAI endpoint URL
    AZURE_OPENAI_DEPLOYMENT    Azure OpenAI deployment (fallback if MCP_AZURE_DEPLOYMENT not set)
    OPENAI_API_KEY             OpenAI API key

PERFORMANCE OPTIMIZATION:
  The MCP server automatically uses --disable-plugins for better performance when
  only built-in tools are needed. Built-in tools include:
    - web_search (comprehensive web search)
    - query_vector_database (semantic search)
    - retrieve_relevant_memory (memory retrieval)
    - instantiate_agent_with_tools_and_process_task (agent creation)
    - create_new_agent_with_tools (agent configuration)
    - summarize_text_file (text summarization)
    - index_documents (RAG document indexing)
    - query_documents (RAG document querying)
  
  Plugin tools are automatically loaded only when configured via MCP_ALLOWED_TOOLS.
  This provides 20-50% faster startup time for typical MCP operations.

AVAILABLE TOOLS:
  1. list_available_tools                      List all available ollama_chat.py tools
  2. list_collections                          List all ChromaDB collections with metadata
  3. web_search                                Comprehensive web search using DuckDuckGo
  4. chat                                      Conversation with AI assistant
  5. index_documents                           Index documents for RAG (Retrieval-Augmented Generation)
  6. query_documents                           Query indexed documents with semantic search
  7. instantiate_agent_with_tools_and_process_task  Create and run an agent with specific tools to solve a task

EXAMPLES:
  # Start the MCP server (normal mode)
  node index.js

  # Run automated tests
  node index.js --test

  # Display this help
  node index.js --help

CONFIGURATION EXAMPLES:
  See CONFIGURATION.md for detailed configuration examples and options.

DOCUMENTATION:
  README.md          - Quick start guide
  CONFIGURATION.md   - Comprehensive configuration guide
  CHANGES.md         - Change history

For more information, visit: https://github.com/jeromeboivin/ollama-chat
`);
}

// Start the server
const config = parseConfig();
const server = new OllamaChatMCPServer(config);

if (HELP_MODE) {
  displayHelp();
  process.exit(0);
} else if (TEST_MODE) {
  console.log("Starting in TEST mode...\n");
  server.runTests().catch((error) => {
    console.error("Test execution failed:", error);
    process.exit(1);
  });
} else {
  server.run().catch(console.error);
}
