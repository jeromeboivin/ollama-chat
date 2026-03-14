"""Application constants and configuration defaults."""

APP_NAME = "ollama-chat"
APP_AUTHOR = ""
APP_VERSION = "1.0.0"

# Default ChromaDB collection names
web_cache_collection_name = "web_cache"

# RAG optimization parameters
# Minimum number of quality results required from cache before skipping web search
min_quality_results_threshold = 5
# Minimum average BM25 score required for cache results to skip web search
# This ensures cached results have lexical/keyword relevance to the query
min_average_bm25_threshold = 0.5
# Minimum hybrid score required for individual results to be considered "quality"
min_hybrid_score_threshold = 0.1
# Percentile threshold for adaptive distance filtering (0-100)
# Results with distance > this percentile will be filtered out
distance_percentile_threshold = 75
# Weight for semantic similarity vs BM25 in hybrid scoring (0.0 to 1.0)
# 0.5 = equal weight, higher = more semantic, lower = more lexical
semantic_weight = 0.5
# Maximum distance multiplier for adaptive threshold
# Results beyond min_distance * this multiplier are filtered
adaptive_distance_multiplier = 2.5

stop_words = ['i', 'me', 'my', 'myself', 'we', 'our', 'ours', 'ourselves', 'you', "you're", "you've", "you'll", "you'd", 'your', 'yours', 'yourself', 'yourselves', 'he', 'him', 'his', 'himself', 'she', "she's", 'her', 'hers', 'herself', 'it', "it's", 'its', 'itself', 'they', 'them', 'their', 'theirs', 'themselves', 'what', 'which', 'who', 'whom', 'this', 'that', "that'll", 'these', 'those', 'am', 'is', 'are', 'was', 'were', 'be', 'been', 'being', 'have', 'has', 'had', 'having', 'do', 'does', 'did', 'doing', 'a', 'an', 'the', 'and', 'but', 'if', 'or', 'because', 'as', 'until', 'while', 'of', 'at', 'by', 'for', 'with', 'about', 'against', 'between', 'into', 'through', 'during', 'before', 'after', 'above', 'below', 'to', 'from', 'up', 'down', 'in', 'out', 'on', 'off', 'over', 'under', 'again', 'further', 'then', 'once', 'here', 'there', 'when', 'where', 'why', 'how', 'all', 'any', 'both', 'each', 'few', 'more', 'most', 'other', 'some', 'such', 'no', 'nor', 'not', 'only', 'own', 'same', 'so', 'than', 'too', 'very', 's', 't', 'can', 'will', 'just', 'don', "don't", 'should', "should've", 'now', 'd', 'll', 'm', 'o', 're', 've', 'y', 'ain', 'aren', "aren't", 'couldn', "couldn't", 'didn', "didn't", 'doesn', "doesn't", 'hadn', "hadn't", 'hasn', "hasn't", 'haven', "haven't", 'isn', "isn't", 'ma', 'mightn', "mightn't", 'mustn', "mustn't", 'needn', "needn't", 'shan', "shan't", 'shouldn', "shouldn't", 'wasn', "wasn't", 'weren', "weren't", 'won', "won't", 'wouldn', "wouldn't"]

# List of available commands to autocomplete
COMMANDS = [
    "/context", "/index", "/verbose", "/cot", "/search", "/web", "/model",
    "/thinking_model", "/model2", "/tools", "/load", "/save", "/collection", "/memory", "/remember",
    "/memorize", "/forget", "/editcollection", "/rmcollection", "/deletecollection", "/chatbot",
    "/think", "/cb", "/file", "/quit", "/exit", "/bye"
]
