"""ChromaDB / vector-database helpers – loading, querying, collection management."""

import os
import re
from datetime import datetime

import chromadb
import ollama
from colorama import Fore, Style
from rank_bm25 import BM25Okapi

from ollama_chat_lib import state
from ollama_chat_lib.io_hooks import on_print, on_user_input
from ollama_chat_lib.constants import (
    web_cache_collection_name, stop_words,
    adaptive_distance_multiplier, distance_percentile_threshold, semantic_weight,
)


def load_chroma_client():
    if state.chroma_client:
        return
    try:
        if state.chroma_db_path:
            os.environ["ANONYMIZED_TELEMETRY"] = "0"
            state.chroma_client = chromadb.PersistentClient(path=state.chroma_db_path)
        elif state.chroma_client_host and 0 < state.chroma_client_port:
            state.chroma_client = chromadb.HttpClient(host=state.chroma_client_host, port=state.chroma_client_port)
        else:
            raise ValueError("Invalid Chroma client configuration")
    except Exception:
        if state.verbose_mode:
            on_print("ChromaDB client could not be initialized. Please check the host and port.", Fore.RED + Style.DIM)
        state.chroma_client = None


def edit_collection_metadata(collection_name):
    load_chroma_client()
    if not collection_name or not state.chroma_client:
        on_print("Invalid collection name or ChromaDB client not initialized.", Fore.RED)
        return
    try:
        state.collection = state.chroma_client.get_collection(name=collection_name)
        if type(state.collection.metadata) == dict:
            current_description = state.collection.metadata.get("description", "No description")
        else:
            current_description = "No description"
        on_print(f"Current description: {current_description}")
        new_description = on_user_input("Enter the new description: ")
        existing_metadata = state.collection.metadata or {}
        existing_metadata["description"] = new_description
        existing_metadata["updated"] = str(datetime.now())
        state.collection.modify(metadata=existing_metadata)
        on_print(f"Description updated for collection {collection_name}.", Fore.GREEN)
    except Exception:
        raise Exception(f"Collection {collection_name} not found")


def prompt_for_vector_database_collection(prompt_create_new=True, include_web_cache=False):
    load_chroma_client()
    collections = None
    if state.chroma_client:
        collections = state.chroma_client.list_collections()
    else:
        on_print("ChromaDB is not running.", Fore.RED)

    if not collections:
        on_print("No collections found", Fore.RED)
        new_collection_name = on_user_input("Enter a new collection to create: ")
        new_collection_desc = on_user_input("Enter a description for the new collection: ")
        return new_collection_name, new_collection_desc

    filtered_collections = []
    for state.collection in collections:
        if state.collection.name == state.memory_collection_name:
            continue
        if state.collection.name == web_cache_collection_name and not include_web_cache:
            continue
        filtered_collections.append(state.collection)

    if not filtered_collections:
        on_print("No collections found", Fore.RED)
        new_collection_name = on_user_input("Enter a new collection to create: ")
        new_collection_desc = on_user_input("Enter a description for the new collection: ")
        return new_collection_name, new_collection_desc

    on_print("Available collections:", Style.RESET_ALL)
    for i, state.collection in enumerate(filtered_collections):
        collection_name = state.collection.name
        if type(state.collection.metadata) == dict:
            collection_metadata = state.collection.metadata.get("description", "No description")
        else:
            collection_metadata = "No description"
        cache_indicator = " (Web Cache)" if collection_name == web_cache_collection_name else ""
        on_print(f"{i}. {collection_name}{cache_indicator} - {collection_metadata}")

    if prompt_create_new:
        on_print(f"{len(filtered_collections)}. Create a new collection")

    choice = int(on_user_input("Enter the number of your preferred collection [0]: ") or 0)

    if prompt_create_new and choice == len(filtered_collections):
        new_collection_name = on_user_input("Enter a new collection to create: ")
        new_collection_desc = on_user_input("Enter a description for the new collection: ")
        return new_collection_name, new_collection_desc

    return filtered_collections[choice].name, None


def set_current_collection(collection_name, description=None, create_new_collection_if_not_found=True, verbose=False):
    load_chroma_client()
    if not collection_name or not state.chroma_client:
        state.collection = None
        state.current_collection_name = None
        return
    try:
        if create_new_collection_if_not_found:
            state.collection = state.chroma_client.get_or_create_collection(
                name=collection_name,
                configuration={
                    "hnsw": {
                        "space": "cosine",
                        "ef_search": 1000,
                        "ef_construction": 1000
                    }
            })
        else:
            state.collection = state.chroma_client.get_collection(name=collection_name)
        if description:
            existing_metadata = state.collection.metadata or {}
            if description != existing_metadata.get("description"):
                existing_metadata["description"] = description
                state.collection.modify(metadata=existing_metadata)
                if verbose:
                    on_print(f"Updated description for collection {collection_name}.", Fore.WHITE + Style.DIM)
        if verbose:
            on_print(f"Collection {collection_name} loaded.", Fore.WHITE + Style.DIM)
        state.current_collection_name = collection_name
    except Exception:
        raise Exception(f"Collection {collection_name} not found")


def delete_collection(collection_name):
    load_chroma_client()
    if not state.chroma_client:
        return
    confirmation = on_user_input(f"Are you sure you want to delete the collection '{collection_name}'? (y/n): ").lower()
    if confirmation != 'y' and confirmation != 'yes':
        on_print("Collection deletion canceled.", Fore.YELLOW)
        return
    try:
        state.chroma_client.delete_collection(name=collection_name)
        on_print(f"Collection {collection_name} deleted.", Fore.GREEN)
    except Exception:
        on_print(f"Collection {collection_name} not found.", Fore.RED)


def preprocess_text(text):
    if not text or len(text) == 0:
        return []
    text = text.lower()
    text = re.sub(r'[^\w\s.,]', ' ', text)
    text = re.sub(r'\. |, ', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    words = text.split()
    words = [word[:-1] if word.endswith('.') else word for word in words]
    words = [word for word in words if word not in stop_words]
    return words


def query_vector_database(question, collection_name=None, n_results=None, answer_distance_threshold=0,
                          query_embeddings_model=None, expand_query=True, question_context=None,
                          use_adaptive_filtering=True, return_metadata=False, ask_fn=None):
    """Query the vector database.  *ask_fn* must be a callable with the same
    signature as ``ask_ollama`` (used for query expansion)."""
    if collection_name is None:
        collection_name = state.current_collection_name
    if n_results is None:
        n_results = state.number_of_documents_to_return_from_vector_db

    if not question or len(question) == 0:
        if return_metadata:
            return "", {}
        return ""

    initial_question = question

    if isinstance(n_results, str):
        try:
            n_results = int(n_results)
        except Exception:
            n_results = state.number_of_documents_to_return_from_vector_db

    if n_results == 0:
        if return_metadata:
            return "", {}
        return ""

    if n_results < 0:
        n_results = state.number_of_documents_to_return_from_vector_db

    if isinstance(answer_distance_threshold, str):
        try:
            answer_distance_threshold = float(answer_distance_threshold)
        except Exception:
            answer_distance_threshold = 0

    if answer_distance_threshold < 0:
        answer_distance_threshold = 0

    if not query_embeddings_model:
        query_embeddings_model = state.embeddings_model

    if not state.collection and collection_name:
        set_current_collection(collection_name, create_new_collection_if_not_found=False)

    if not state.collection:
        on_print("No ChromaDB collection loaded.", Fore.RED)
        collection_name, _ = prompt_for_vector_database_collection()
        if not collection_name:
            if return_metadata:
                return "", {}
            return ""

    if collection_name and collection_name != state.current_collection_name:
        set_current_collection(collection_name, create_new_collection_if_not_found=False)

    if expand_query:
        if ask_fn is None:
            raise ValueError("ask_fn is required for query expansion")
        expanded_query = None
        system_prompt = "You are an assistant that helps expand and clarify user questions to improve information retrieval. When a user provides a question, your task is to write a short passage that elaborates on the query by adding relevant background information, inferred details, and related concepts that can help with retrieval. The passage should remain concise and focused, without changing the original meaning of the question.\r\nGuidelines:\r\n1. Expand the question briefly by including additional context or background, staying relevant to the user's original intent.\r\n2. Incorporate inferred details or related concepts that help clarify or broaden the query in a way that aids retrieval.\r\n3. Keep the passage short, usually no more than 2-3 sentences, while maintaining clarity and depth.\r\n4. Avoid introducing unrelated or overly specific topics. Keep the expansion concise and to the point."
        if question_context:
            system_prompt += f"\n\nAdditional context about the user query:\n{question_context}"

        if not state.thinking_model is None and state.thinking_model != state.current_model:
            if "deepseek-r1" in state.thinking_model:
                prompt = f"""{system_prompt}\n{question}"""
                expanded_query = ask_fn("", prompt, selected_model=state.thinking_model, no_bot_prompt=True, stream_active=False)
            else:
                expanded_query = ask_fn(system_prompt, question, selected_model=state.thinking_model, no_bot_prompt=True, stream_active=False)
        else:
            expanded_query = ask_fn(system_prompt, question, selected_model=state.current_model, no_bot_prompt=True, stream_active=False)
        if expanded_query:
            question += "\n" + expanded_query
            if state.verbose_mode:
                on_print("Expanded query:", Fore.WHITE + Style.DIM)
                on_print(question, Fore.WHITE + Style.DIM)

    if state.verbose_mode:
        on_print(f"Using query embeddings model: {query_embeddings_model}", Fore.WHITE + Style.DIM)

    if query_embeddings_model is None:
        result = state.collection.query(
            query_texts=[question],
            n_results=25
        )
    else:
        response = ollama.embeddings(
            prompt=question,
            model=query_embeddings_model
        )
        result = state.collection.query(
            query_embeddings=[response["embedding"]],
            n_results=25
        )

    documents = result["documents"][0]
    distances = result["distances"][0]

    if len(result["metadatas"]) == 0:
        if return_metadata:
            return "", {}
        return ""

    if len(result["metadatas"][0]) == 0:
        if return_metadata:
            return "", {}
        return ""

    metadatas = result["metadatas"][0]

    if use_adaptive_filtering and len(distances) > 0:
        min_distance = min(distances) if distances else 0
        adaptive_threshold = min_distance * adaptive_distance_multiplier
        if len(distances) >= 4:
            try:
                import numpy as np
                percentile_threshold = np.percentile(distances, distance_percentile_threshold)
                effective_threshold = max(adaptive_threshold, percentile_threshold)
            except Exception:
                effective_threshold = adaptive_threshold
        else:
            effective_threshold = adaptive_threshold
        if state.verbose_mode:
            on_print(f"Adaptive distance threshold: {effective_threshold:.4f} (min: {min_distance:.4f}, adaptive: {adaptive_threshold:.4f}, percentile: {percentile_threshold if len(distances) >= 4 else 'N/A'})", Fore.WHITE + Style.DIM)
    else:
        effective_threshold = float('inf')

    initial_question_preprocessed = preprocess_text(initial_question)
    preprocessed_docs = [preprocess_text(doc) for doc in documents]

    bm25 = BM25Okapi(preprocessed_docs)
    bm25_scores = bm25.get_scores(initial_question_preprocessed)

    max_dist = max(distances) if len(distances) > 0 and max(distances) > 0 else 1
    normalized_semantic_scores = [1 - (d / max_dist) for d in distances]

    bm25_scores_list = list(bm25_scores) if hasattr(bm25_scores, '__iter__') else []
    max_bm25 = max(bm25_scores_list) if len(bm25_scores_list) > 0 and max(bm25_scores_list) > 0 else 1
    normalized_bm25_scores = [score / max_bm25 for score in bm25_scores_list]

    hybrid_scores = [
        semantic_weight * sem + (1 - semantic_weight) * lex
        for sem, lex in zip(normalized_semantic_scores, normalized_bm25_scores)
    ]

    reranked_results = []
    for idx, (metadata, distance, document, bm25_score, hybrid_score) in enumerate(
        zip(metadatas, distances, documents, bm25_scores_list, hybrid_scores)
    ):
        if use_adaptive_filtering and distance > effective_threshold:
            if state.verbose_mode:
                on_print(f"Filtered out result with distance {distance:.4f} > {effective_threshold:.4f}", Fore.WHITE + Style.DIM)
            continue
        if answer_distance_threshold > 0 and distance > answer_distance_threshold:
            if state.verbose_mode:
                on_print(f"Filtered out result with distance {distance:.4f} > {answer_distance_threshold:.4f}", Fore.WHITE + Style.DIM)
            continue
        reranked_results.append((idx, metadata, distance, document, bm25_score, hybrid_score))

    reranked_results.sort(key=lambda x: x[5], reverse=True)
    reranked_results = reranked_results[:n_results]

    answers = []
    metadata_list = []

    for idx, metadata, distance, document, bm25_score, hybrid_score in reranked_results:
        if state.verbose_mode:
            on_print(f"Result - Distance: {distance:.4f}, BM25: {bm25_score:.4f}, Hybrid: {hybrid_score:.4f}", Fore.WHITE + Style.DIM)

        title = metadata.get("title", "")
        url = metadata.get("url", "")
        filePath = metadata.get("filePath", "")

        formatted_answer = document
        if title:
            formatted_answer = title + "\n" + formatted_answer
        if url:
            formatted_answer += "\nURL: " + url
        if filePath:
            formatted_answer += "\nFile Path: " + filePath

        answers.append(formatted_answer.strip())

        if return_metadata:
            metadata_list.append({
                'distance': distance,
                'bm25_score': bm25_score,
                'hybrid_score': hybrid_score,
                'metadata': metadata,
                'has_full_document': False
            })

    result_text = '\n\n'.join(answers)

    if return_metadata:
        avg_bm25 = sum(x[4] for x in reranked_results) / len(reranked_results) if reranked_results else 0.0
        avg_hybrid = sum(x[5] for x in reranked_results) / len(reranked_results) if reranked_results else 0.0
        avg_distance = sum(x[2] for x in reranked_results) / len(reranked_results) if reranked_results else 0.0
        return result_text, {
            'num_results': len(answers),
            'results': metadata_list,
            'effective_threshold': effective_threshold if use_adaptive_filtering else None,
            'avg_bm25_score': avg_bm25,
            'avg_hybrid_score': avg_hybrid,
            'avg_distance': avg_distance,
            'full_documents_retrieved': 0
        }

    return result_text
