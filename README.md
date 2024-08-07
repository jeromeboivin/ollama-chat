# ollama-chat

A CLI-based Python script that interacts with a local Language Model (LLM) through `Ollama` and `Llama-Cpp` servers. It also supports the use of a local or distant `ChromaDB` vector database for the RAG (Retrieval-Augmented Generation) model, providing a more efficient and flexible way to generate responses.

## Prerequisites

Before you can run the `ollama_chat.py` script, you need to install several Python packages. These packages provide the necessary functionality for the script to interact with the Ollama language model, the ChromaDB vector database, and other features.

Here is the list of required packages:

- `ollama`: This package allows the script to interact with the Ollama server.
- `colorama`: This package is used for colored terminal text.
- `chromadb`: This package enables the script to interact with the ChromaDB vector database.
- `pywin32`: This package provides access to some useful APIs on Windows like clipboard.
- `pyperclip`: This package provides access to clipboard (Linux and MacOS).
- `pygments`: This package is used for syntax highlighting.
- `duckduckgo_search`: This package allows the script to perform DuckDuckGo searches.

You can install all these packages using pip, the Python package installer. Run the following command in your terminal:

```bash
pip install ollama colorama chromadb pygments duckduckgo_search
```

Additionally, under Windows platform, install `pywin32`:

```bash
pip install pywin32
```

## How to Use the Ollama Chatbot Script

This guide will explain how to use the `ollama_chat.py` script. This script is designed to act as a terminal-based user interface for Ollama and it accepts several command-line arguments to customize its behavior.

Here's a step-by-step guide on how to use it:

1. **Run the script**: You can run the script using Python. The command to run the script is `python ollama_chat.py`. This will run the script with all default settings.

2. **Specify ChromaDB client host and port**: If you want to specify the ChromaDB client host and port, you can use the `--chroma-host` and `--chroma-port` arguments. For example, `python ollama_chat.py --chroma-host myhost --chroma-port 1234`.

3. **Specify the ChromaDB collection name**: Use the `--collection` argument to specify the ChromaDB collection name. For example, `python ollama_chat.py --collection mycollection`.

4. **Use Ollama or OpenAI API (Llama-CPP)**: By default, the script uses Ollama. If you want to use the OpenAI API, use the `--use-openai` argument. For example, `python ollama_chat.py --use-openai`.

5. **Set the temperature for the model**: You can set the temperature using the `--temperature` argument. For example, `python ollama_chat.py --temperature 0.8`.

6. **Disable the system role**: If the selected model does not support the system role, like Google Gemma models, use the `--disable-system-role` argument. For example, `python ollama_chat.py --disable-system-role`.

7. **Specify the prompt template for Llama-CPP**: Use the `--prompt-template` argument to specify the prompt template for Llama-CPP. For example, `python ollama_chat.py --prompt-template "ChatML"`.

8. **Specify the path to a JSON file containing additional chatbots**: Use the `--additional-chatbots` argument to specify the path to a JSON file containing additional chatbots. For example, `python ollama_chat.py --additional-chatbots /path/to/chatbots.json`.

9. **Enable verbose mode**: If you want to enable verbose mode, use the `--verbose` argument. For example, `python ollama_chat.py --verbose`.

10. **Specify the Ollama sentence embeddings model**: Use the `--embeddings-model` argument to specify the sentence embeddings model to use for vector database queries. For example, `python ollama_chat.py --embeddings-model mxbai-embed-large`.

11. **Specify a system prompt message**: Use the `--system-prompt` argument to specify a system prompt message. For example, `python ollama_chat.py --system-prompt "You are a teacher teaching physics, you must not give the answers but ask questions to guide the student in order to find the answer."`.

12. **Specify the Ollama model to use**: Use the `--model` argument to specify the Ollama model to be used. Default model: `phi3:mini`.

13. **Specify the folder to save conversations to**: Use the `--conversations-folder <folder-path>` to specify the folder to save conversations to. If not specified, conversations will be saved in the current directory.

14. **Save the conversation automatically**: Use the `--auto-save` argument to automatically saves the conversation when exiting the program.

15. **Index a local folder to the current ChromaDB collection**: Use the `--index-documents` to specify the root folder containing text files to index.

Remember, all these arguments are optional. If you don't specify them, the script will use the default values.

## How to Use Special Switches

The Ollama client supports several special switches to enhance your interaction with the chatbot. Here's a brief guide on how to use them:

1. `/file <path of a file to load>`: This command allows you to read a file and append its content to your user input. Replace <path of a file to load> with the actual path of the file you want to load.

2. `/search <number of results>`: This command lets you query the vector database and append the answer to your user input. Replace <number of results> with the number of search results you want to retrieve.

3. `/web`: This command performs a web search using DuckDuckGo.

4. `/model`: This command allows you to change the Ollama model.

5. `/chatbot`: This command lets you change the chatbot personality.

6. `/collection`: This command allows you to change the vector database collection.

7. `/index <folder path>`: Index text files in the specified folder to current vector database collection.

8. `/cb`: This command replaces /cb with the content of your clipboard.

9. `/save <path of saved conversation>`: Saves the conversation to a specified file path.

10. `/verbose`: This command toggles verbose mode on or off.

11. `/reset`, `/clear`, `/restart`: These commands reset the conversation, clearing all previous inputs and responses.

12. `/quit`, `/exit`, `/bye`: These commands exit the chatbot.

Remember to precede each command with a forward slash `(/)` and follow it with the appropriate parameters if necessary.

## Redirecting standard input from the console

The script can be used by redirecting standard input from the console. This allows you to pass input to the script without manually typing it in. 

Use the `--no-interactive` command-line switch to deactivate any prompt.

Here's an example:

```bash
echo "why is the sky blue?" | python ollama_chat.py --no-interactive
```

In this example, the echo command is used to create a string "why is the sky blue?". The pipe operator (|) then redirects this string as input to the ollama_chat.py script.

This way of using the script can be very useful when you want to automate the process of sending input to the script or when you want to use the script in a larger pipeline of commands.

## Generating text descriptions from images with vision models

Model used in this example: `llava-phi3`.

- **User**: *Describe this image and try to guess where the photo was taken /file '/path/to/_MG_5527.jpg'*
- **Bot**: `without additional information, it's difficult to pinpoint the exact location.`
- **User**: *make some propositions anyway*. Still no answer regarding possible location.
- **User**: *based on the image description and previous propositions, guess where the photo was taken please*
- **Bot**: `The presence of brick buildings and canals are common features found in European cities such as Venice, Amsterdam, or Bruges.`

![Boat on a canal picture](_MG_5527.jpg)

![Image descrition generated by llava-phi3](llava-phi3.png)

### Using non-interactive mode

- Use the `--no-interactive` command-line switch to deactivate any prompt, and possibly redirect output to a file or another process:

```bash
$ echo "Guess where this picture was taken. /file '_MG_5527.jpg'" | python3 ollama_chat.py --no-interactive --model llava-phi3
```

Output:

```
The image was likely taken in a canal or waterway, possibly in Venice, Italy. This is suggested by the presence of a boat and stairs leading down to the water, which are common features in Venetian canals. Additionally, the brick wall and arched doorway also hint at an old European cityscape. The blue and red boat with a yellow stripe adds a vibrant touch to the scene, further enhancing its charm and appeal.The image was likely taken in a canal or waterway, possibly in Venice, Italy. This is suggested by the presence of a boat and stairs leading down to the water, which are common features in Venetian canals. Additionally, the brick wall and arched doorway also hint at an old European cityscape. The blue and red boat with a yellow stripe adds a vibrant touch to the scene, further enhancing its charm and appeal.
```

## Web search using DuckDuckGo

![ollama-chat in PowerShell](ollama-chat.png)

## How to Specify Custom Chatbot Personalities in JSON Format

Use the `--additional-chatbots` to specify the path to a JSON file containing additional pre-defined chatbots. This JSON file has to be an array of objects specifying these chatbots properties:

1. **description**: This is a brief explanation of the chatbot's purpose. It should be a string that describes what the chatbot is designed to do.

2. **name**: This is the name of the chatbot. It should be a string that uniquely identifies the chatbot.

3. **preferred_model**: This is the model that the chatbot uses to generate responses. It should be a string that specifies the Ollama model's name.

4. **system_prompt**: This is the initial prompt that the chatbot uses to start a conversation. It should be a string that describes the chatbot's role and provides some context for the conversation. It can also include a list of possible prompt commands that the chatbot can use.

**Note**: special token `{possible_prompt_commands}` in the system prompt will be replaced by the possible commands automatically (see [How to Use Special Switches] section above).

Here is an example of a JSON file that specifies a custom chatbot personality:

```json
[
    {
        "description": "Chatbot for code-related questions",
        "name": "code",
        "preferred_model": "wizardlm2:latest",
        "system_prompt": "You are a helpful chatbot assistant for software developers. If not specified, assume questions about code and APIs are in TypeScript. Possible chatbot prompt commands: {possible_prompt_commands}"
    }
]
```
