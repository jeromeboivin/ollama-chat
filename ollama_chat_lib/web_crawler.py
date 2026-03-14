"""Web crawling and scraping classes."""
import base64
import getpass
import os

import requests
import chardet
from bs4 import BeautifulSoup
from colorama import Fore, Style
from markdownify import MarkdownConverter  # noqa: F401 — used by extract_text_from_html
from urllib.parse import urljoin, urlparse

from ollama_chat_lib.io_hooks import on_print
from ollama_chat_lib.text_extraction import extract_text_from_html, extract_text_from_pdf


class SimpleWebCrawler:
    def __init__(self, urls, llm_enabled=False, system_prompt='', selected_model='', temperature=0.1, verbose=False, plugins=[], num_ctx=None, ask_fn=None):
        self.urls = urls
        self.articles = []
        self.llm_enabled = llm_enabled
        self.system_prompt = system_prompt
        self.selected_model = selected_model
        self.temperature = temperature
        self.verbose = verbose
        self.plugins = plugins
        self.num_ctx = num_ctx
        self._ask_fn = ask_fn

    def fetch_page(self, url):
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            return response.content
        except requests.exceptions.RequestException as e:
            if self.verbose:
                on_print(f"Error fetching URL {url}: {e}", Fore.RED)
            return None

    def ask_llm(self, content, user_input):
        user_input = content + "\n\n" + user_input
        if self._ask_fn is None:
            raise RuntimeError("ask_fn not set on SimpleWebCrawler")
        return self._ask_fn(system_prompt=self.system_prompt,
                            user_input=user_input,
                            selected_model=self.selected_model,
                            temperature=self.temperature,
                            prompt_template=None,
                            tools=[],
                            no_bot_prompt=True,
                            stream_active=self.verbose,
                            num_ctx=self.num_ctx)

    def decode_content(self, content):
        detected_encoding = chardet.detect(content)['encoding']
        if self.verbose:
            on_print(f"Detected encoding: {detected_encoding}", Fore.WHITE + Style.DIM)

        try:
            return content.decode(detected_encoding)
        except (UnicodeDecodeError, TypeError):
            if self.verbose:
                on_print(f"Error decoding content with {detected_encoding}, using ISO-8859-1 as fallback.", Fore.RED)
            return content.decode('ISO-8859-1')

    def crawl(self, task=None):
        for url in self.urls:
            continue_response_generation = True
            for plugin in self.plugins:
                if hasattr(plugin, "stop_generation") and callable(getattr(plugin, "stop_generation")):
                    plugin_response = getattr(plugin, "stop_generation")()
                    if plugin_response:
                        continue_response_generation = False
                        break

            if not continue_response_generation:
                break

            if self.verbose:
                on_print(f"Fetching URL: {url}", Fore.WHITE + Style.DIM)
            content = self.fetch_page(url)
            if content:
                if url.lower().endswith('.pdf'):
                    if self.verbose:
                        on_print(f"Extracting text from PDF: {url}", Fore.WHITE + Style.DIM)
                    extracted_text = extract_text_from_pdf(content)
                else:
                    if self.verbose:
                        on_print(f"Extracting text from HTML: {url}", Fore.WHITE + Style.DIM)
                    decoded_content = self.decode_content(content)
                    extracted_text = extract_text_from_html(decoded_content)

                article = {'url': url, 'text': extracted_text}

                if self.llm_enabled and task:
                    if self.verbose:
                        on_print(Fore.WHITE + Style.DIM + f"Using LLM to process the content. Task: {task}")
                    llm_result = self.ask_llm(content=extracted_text, user_input=task)
                    article['llm_result'] = llm_result

                self.articles.append(article)

    def get_articles(self):
        return self.articles


class SimpleWebScraper:
    def __init__(self, base_url, output_dir="downloaded_site", file_types=None, restrict_to_base=True, convert_to_markdown=False, verbose=False):
        self.base_url = base_url.rstrip('/')
        self.output_dir = output_dir
        self.file_types = file_types if file_types else ["html", "jpg", "jpeg", "png", "gif", "css", "js"]
        self.restrict_to_base = restrict_to_base
        self.convert_to_markdown = convert_to_markdown
        self.visited = set()
        self.verbose = verbose
        self.username = None
        self.password = None

    def scrape(self, url=None, depth=0, max_depth=50):
        if url is None:
            url = self.base_url

        if depth > max_depth and self.verbose:
            on_print(f"Max depth reached for {url}")
            return

        url = self._normalize_url(url)

        if url in self.visited:
            return
        self.visited.add(url)

        if self.verbose:
            on_print(f"Scraping: {url}")
        response = self._fetch(url)
        if not response:
            return

        content_type = response.headers.get("Content-Type", "")
        if "text/html" in content_type or not self._has_extension(url):
            if self.convert_to_markdown:
                self._save_markdown(url, response.text)
            else:
                self._save_html(url, response.text)
            self._parse_and_scrape_links(response.text, url, depth + 1)
        else:
            if self._is_allowed_file_type(url):
                self._save_file(url, response.content)

    def _fetch(self, url):
        headers = {}
        if self.username and self.password:
            credentials = f"{self.username}:{self.password}"
            encoded_credentials = base64.b64encode(credentials.encode('utf-8')).decode('utf-8')
            headers['Authorization'] = f"Basic {encoded_credentials}"

        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 401:
                on_print(f"Unauthorized access to {url}. Please enter your credentials.", Fore.RED)
                self.username = input("Username: ")
                self.password = getpass.getpass("Password: ")
                credentials = f"{self.username}:{self.password}"
                encoded_credentials = base64.b64encode(credentials.encode('utf-8')).decode('utf-8')
                headers['Authorization'] = f"Basic {encoded_credentials}"
                response = requests.get(url, headers=headers, timeout=10)
                response.raise_for_status()
            return response
        except requests.RequestException as e:
            on_print(f"Failed to fetch {url}: {e}", Fore.RED)
            return None

    def _save_html(self, url, html):
        local_path = self._get_local_path(url)
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        with open(local_path, "w", encoding="utf-8") as file:
            file.write(html)

    def _save_markdown(self, url, html):
        local_path = self._get_local_path(url, markdown=True)
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        markdown_content = extract_text_from_html(html)
        with open(local_path, "w", encoding="utf-8") as file:
            file.write(markdown_content)

    def _save_file(self, url, content):
        local_path = self._get_local_path(url)
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        with open(local_path, "wb") as file:
            file.write(content)

    def _get_local_path(self, url, markdown=False):
        parsed_url = urlparse(url)
        local_path = os.path.join(self.output_dir, parsed_url.netloc, parsed_url.path.lstrip('/'))
        if local_path.endswith('/') or not os.path.splitext(parsed_url.path)[1]:
            local_path = os.path.join(local_path, "index.md" if markdown else "index.html")
        elif markdown:
            local_path = os.path.splitext(local_path)[0] + ".md"
        return local_path

    def _normalize_url(self, url):
        parsed = urlparse(url)
        normalized = parsed._replace(fragment="").geturl()
        return normalized

    def _parse_and_scrape_links(self, html, base_url, depth):
        soup = BeautifulSoup(html, "html.parser")

        for tag, attr in [("a", "href"), ("img", "src"), ("link", "href"), ("script", "src")]:
            for element in soup.find_all(tag):
                link = element.get(attr)
                if link:
                    abs_link = urljoin(base_url, link)
                    abs_link = self._normalize_url(abs_link)
                    if self.restrict_to_base and not self._is_same_domain(abs_link):
                        continue
                    if not self._is_allowed_file_type(abs_link) and self._has_extension(abs_link):
                        continue
                    if abs_link not in self.visited:
                        self.scrape(abs_link, depth=depth)

    def _is_same_domain(self, url):
        base_domain = urlparse(self.base_url).netloc
        target_domain = urlparse(url).netloc
        return base_domain == target_domain

    def _is_allowed_file_type(self, url):
        path = urlparse(url).path
        file_extension = os.path.splitext(path)[1].lstrip('.').lower()
        return file_extension in self.file_types

    def _has_extension(self, url):
        path = urlparse(url).path
        return bool(os.path.splitext(path)[1])
