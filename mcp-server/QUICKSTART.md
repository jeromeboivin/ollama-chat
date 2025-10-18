# Quick Start Guide - Multi-Provider Setup

## 🚀 Choose Your Setup

### Option 1: Auto Mode (Recommended for Most Users)

**Best for**: Users who want automatic provider selection based on available credentials

**Setup**: Just set your API credentials as environment variables, and the server handles the rest!

#### Windows (PowerShell)
```powershell
# For Azure OpenAI (highest priority)
$env:AZURE_OPENAI_API_KEY = "your-key-here"
$env:AZURE_OPENAI_ENDPOINT = "https://your-resource.openai.azure.com/"
$env:AZURE_OPENAI_DEPLOYMENT = "gpt-4"

# OR for OpenAI (medium priority)
$env:OPENAI_API_KEY = "sk-your-key-here"

# OR use Ollama (no setup needed - just run Ollama)
```

#### macOS/Linux
```bash
# For Azure OpenAI (highest priority)
export AZURE_OPENAI_API_KEY="your-key-here"
export AZURE_OPENAI_ENDPOINT="https://your-resource.openai.azure.com/"
export AZURE_OPENAI_DEPLOYMENT="gpt-4"

# OR for OpenAI (medium priority)
export OPENAI_API_KEY="sk-your-key-here"

# OR use Ollama (no setup needed - just run Ollama)
```

#### Claude Desktop Config
```json
{
  "mcpServers": {
    "ollama-chat": {
      "command": "node",
      "args": ["C:\\path\\to\\ollama-chat\\mcp-server\\index.js"]
    }
  }
}
```

✅ That's it! The server will automatically use the best available provider.

---

### Option 2: Force a Specific Provider

**Best for**: Production environments, compliance requirements, or testing specific providers

#### Force Azure OpenAI

**Claude Desktop Config** (`%APPDATA%\Claude\claude_desktop_config.json` on Windows):
```json
{
  "mcpServers": {
    "ollama-chat": {
      "command": "node",
      "args": ["C:\\path\\to\\ollama-chat\\mcp-server\\index.js"],
      "env": {
        "MCP_PROVIDER": "azure",
        "AZURE_OPENAI_API_KEY": "your-key",
        "AZURE_OPENAI_ENDPOINT": "https://your-resource.openai.azure.com/",
        "AZURE_OPENAI_DEPLOYMENT": "gpt-4"
      }
    }
  }
}
```

#### Force OpenAI

```json
{
  "mcpServers": {
    "ollama-chat": {
      "command": "node",
      "args": ["C:\\path\\to\\ollama-chat\\mcp-server\\index.js"],
      "env": {
        "MCP_PROVIDER": "openai",
        "OPENAI_API_KEY": "sk-your-key-here"
      }
    }
  }
}
```

#### Force Ollama (Local, Private)

```json
{
  "mcpServers": {
    "ollama-chat": {
      "command": "node",
      "args": ["C:\\path\\to\\ollama-chat\\mcp-server\\index.js"],
      "env": {
        "MCP_PROVIDER": "ollama"
      }
    }
  }
}
```

---

### Option 3: Multiple Providers (Dev/Prod Setup)

**Best for**: Developers who want to test with different providers

**Claude Desktop Config**:
```json
{
  "mcpServers": {
    "ollama-local": {
      "command": "node",
      "args": ["C:\\path\\to\\ollama-chat\\mcp-server\\index.js"],
      "env": {
        "MCP_PROVIDER": "ollama"
      }
    },
    "ollama-azure": {
      "command": "node",
      "args": ["C:\\path\\to\\ollama-chat\\mcp-server\\index.js"],
      "env": {
        "MCP_PROVIDER": "azure",
        "AZURE_OPENAI_API_KEY": "your-key",
        "AZURE_OPENAI_ENDPOINT": "https://your-resource.openai.azure.com/",
        "AZURE_OPENAI_DEPLOYMENT": "gpt-4"
      }
    },
    "ollama-openai": {
      "command": "node",
      "args": ["C:\\path\\to\\ollama-chat\\mcp-server\\index.js"],
      "env": {
        "MCP_PROVIDER": "openai",
        "OPENAI_API_KEY": "sk-your-key-here"
      }
    }
  }
}
```

This gives you three separate MCP servers, each using a different provider!

---

## ✅ Verify Your Setup

1. **Test the server**:
   ```bash
   cd mcp-server
   npm test
   ```

2. **Check which provider is being used**:
   Look for a line like:
   ```
   [Info] Using Azure OpenAI (auto-detected from environment variables)
   ```

3. **Restart Claude Desktop** after making config changes

4. **Check Claude Desktop logs** if something isn't working:
   - Windows: `%APPDATA%\Claude\logs\`
   - macOS: `~/Library/Logs/Claude/`

---

## 🎯 Common Scenarios

### I want to use Azure OpenAI
1. Get your Azure OpenAI credentials
2. Set all three environment variables (API key, endpoint, deployment)
3. Use auto mode or force Azure with `MCP_PROVIDER="azure"`

### I want to use OpenAI
1. Get your OpenAI API key
2. Set `OPENAI_API_KEY` environment variable
3. Use auto mode or force OpenAI with `MCP_PROVIDER="openai"`

### I want privacy (local only)
1. Install and run Ollama
2. Set `MCP_PROVIDER="ollama"` to ensure cloud providers are never used
3. No API keys needed!

### I want to test different providers
1. Create multiple MCP server entries in Claude config
2. Each with a different `MCP_PROVIDER` setting
3. Use whichever one you need at the moment

### I want automatic failover
1. Don't set `MCP_PROVIDER` (use auto mode)
2. Set multiple provider credentials
3. Server will use Azure → OpenAI → Ollama in that order

---

## 🔧 Troubleshooting

**Problem**: "Azure OpenAI provider selected but required environment variables are missing"

**Solution**: Make sure ALL THREE Azure variables are set:
- `AZURE_OPENAI_API_KEY`
- `AZURE_OPENAI_ENDPOINT`
- `AZURE_OPENAI_DEPLOYMENT`

---

**Problem**: Server keeps using wrong provider

**Solution**: Set `MCP_PROVIDER` explicitly to override auto-detection

---

**Problem**: Can't see which provider is being used

**Solution**: 
1. Run `npm test` in the mcp-server directory
2. Or check Claude Desktop logs

---

**Problem**: Changes not taking effect

**Solution**: Restart Claude Desktop after config changes!

---

## 📚 More Information

- **Detailed guide**: See `PROVIDER_CONFIGURATION.md`
- **Full README**: See `README.md`
- **Change log**: See `CHANGES.md`

## 🎉 You're All Set!

Your MCP server now supports multiple AI providers. Choose the setup that works best for you and enjoy seamless AI-powered web search and chat!
