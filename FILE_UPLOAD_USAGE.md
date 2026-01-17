# File Upload Feature for OpenAI/Azure OpenAI

This document describes how to use the new file upload feature with OpenAI and Azure OpenAI APIs.

## Overview

The program now supports sending files (including PDFs and images) as base64-encoded data to OpenAI and Azure OpenAI using the Responses API endpoint (`/openai/v1/responses`).

## Supported File Types

When using OpenAI or Azure OpenAI, the following file types will be sent as base64 attachments:
- **Images**: `.png`, `.jpg`, `.jpeg`, `.bmp`, `.gif`, `.webp`
- **Documents**: `.pdf`

## Usage

### Using the `/file` Command

Simply use the `/file` command followed by the path to your file:

```
/file path/to/document.pdf Summarize this document
```

or

```
What is in this image? /file path/to/image.png
```

### Example Sessions

#### Analyzing a PDF Document

```
User: /file contract.pdf What are the key terms in this contract?
Bot: [The model will receive the PDF and analyze it]
```

#### Analyzing an Image

```
User: /file screenshot.png Explain what's happening in this screenshot
Bot: [The model will receive the image and describe it]
```

## How It Works

1. **File Detection**: When you use `/file` with OpenAI or Azure OpenAI, the program checks the file extension.

2. **Binary Files**: For PDFs and images, the file is read as binary and encoded to base64.

3. **Responses API**: Instead of the standard chat completions endpoint, the program uses the Responses API (`/openai/v1/responses`) which supports the `input_file` content type.

4. **Request Format**: The file is sent with the structure:
   ```json
   {
     "type": "input_file",
     "filename": "document.pdf",
     "file_data": "data:application/pdf;base64,<base64-encoded-data>"
   }
   ```

## Configuration

### Azure OpenAI

Set these environment variables:
```bash
export AZURE_OPENAI_API_KEY="your-api-key"
export AZURE_OPENAI_ENDPOINT="https://your-resource.openai.azure.com"
export AZURE_OPENAI_DEPLOYMENT="your-deployment-name"
```

Then run with:
```bash
python ollama_chat.py --azure-openai
```

### OpenAI

Set your API key:
```bash
export OPENAI_API_KEY="your-api-key"
```

Then run with:
```bash
python ollama_chat.py --openai
```

## Model Requirements

- For Azure OpenAI: Use models that support both text and vision, such as `gpt-4o` or `gpt-4o-mini`
- For OpenAI: Use vision-capable models like `gpt-4-vision-preview`, `gpt-4o`, or `gpt-4o-mini`

## Limitations

1. **File Size**: Large files may exceed token limits. The entire file is encoded and sent with each request.

2. **Token Usage**: Text and images extracted from PDFs count against your token limits.

3. **Model Support**: Only vision-capable models can process PDFs and images.

4. **Streaming**: The Responses API doesn't support streaming in the same way as chat completions.

## Technical Details

### Implementation

The implementation includes three main components:

1. **`encode_file_to_base64_with_mime(file_path)`**: Encodes files to base64 with proper MIME type prefix

2. **`ask_openai_responses_api(conversation, ...)`**: Makes HTTP requests to the Responses API endpoint

3. **Modified `/file` handling**: Detects when files should be sent as attachments vs. read as text

### API Endpoint

- **Azure OpenAI**: `https://{resource}.openai.azure.com/openai/v1/responses`
- **OpenAI**: `https://api.openai.com/v1/responses`

### Request Structure

```json
{
  "model": "gpt-4o-mini",
  "input": [
    {
      "role": "user",
      "content": [
        {
          "type": "input_file",
          "filename": "document.pdf",
          "file_data": "data:application/pdf;base64,..."
        },
        {
          "type": "input_text",
          "text": "Your question or instruction"
        }
      ]
    }
  ],
  "temperature": 0.1
}
```

## Troubleshooting

### "Invalid image URL" Error

This means the chat completions endpoint was used instead of the Responses API. Make sure:
- You're using OpenAI or Azure OpenAI (not Ollama)
- The file has a supported extension
- The file exists at the specified path

### "Error calling Responses API"

Check:
- Your API key and endpoint are correctly configured
- Your model deployment supports vision/file inputs
- The file isn't too large
- You have proper network connectivity

### Verbose Mode

Use `--verbose` to see detailed information about API calls:
```bash
python ollama_chat.py --openai --verbose
```

This will show:
- When files are detected
- The API endpoint being called
- Request and response details

## Backward Compatibility

For Ollama models:
- Images (`.png`, `.jpg`, `.jpeg`, `.bmp`) are still sent using the native Ollama image support
- PDFs and other files are read as text and included in the prompt
- The behavior remains unchanged from previous versions
