"""Tests for SimpleWebCrawler."""
import pytest
from unittest.mock import patch, MagicMock
import ollama_chat as oc
from ollama_chat_lib import state


class TestSimpleWebCrawler:

    def test_init_stores_urls(self):
        crawler = oc.SimpleWebCrawler(["http://example.com"])
        assert crawler.urls == ["http://example.com"]
        assert crawler.articles == []

    def test_fetch_page_success(self):
        crawler = oc.SimpleWebCrawler(["http://example.com"])
        mock_resp = MagicMock()
        mock_resp.content = b"<html>Hello</html>"
        mock_resp.raise_for_status = MagicMock()
        with patch("ollama_chat_lib.web_crawler.requests.get", return_value=mock_resp):
            result = crawler.fetch_page("http://example.com")
        assert result == b"<html>Hello</html>"

    def test_fetch_page_failure(self):
        crawler = oc.SimpleWebCrawler(["http://bad.com"], verbose=False)
        import requests
        with patch("ollama_chat_lib.web_crawler.requests.get", side_effect=requests.exceptions.ConnectionError("fail")):
            result = crawler.fetch_page("http://bad.com")
        assert result is None

    def test_decode_content_utf8(self):
        crawler = oc.SimpleWebCrawler([])
        with patch("ollama_chat_lib.web_crawler.chardet.detect", return_value={"encoding": "utf-8"}):
            result = crawler.decode_content("Hello".encode("utf-8"))
        assert result == "Hello"

    def test_decode_content_fallback(self):
        crawler = oc.SimpleWebCrawler([], verbose=False)
        with patch("ollama_chat_lib.web_crawler.chardet.detect", return_value={"encoding": None}):
            result = crawler.decode_content("Hello".encode("latin-1"))
        assert "Hello" in result

    def test_crawl_html(self, reset_globals):
        state.plugins = []
        crawler = oc.SimpleWebCrawler(["http://example.com"], verbose=False, plugins=[])
        mock_resp = MagicMock()
        mock_resp.content = b"<html><body><p>Content</p></body></html>"
        mock_resp.raise_for_status = MagicMock()
        with patch("ollama_chat_lib.web_crawler.requests.get", return_value=mock_resp):
            with patch("ollama_chat_lib.web_crawler.chardet.detect", return_value={"encoding": "utf-8"}):
                crawler.crawl()
        assert len(crawler.articles) == 1
        assert "Content" in crawler.articles[0]["text"]

    def test_crawl_pdf_url(self, reset_globals):
        state.plugins = []
        crawler = oc.SimpleWebCrawler(["http://example.com/doc.pdf"], verbose=False, plugins=[])
        mock_resp = MagicMock()
        mock_resp.content = b"fake-pdf-bytes"
        mock_resp.raise_for_status = MagicMock()
        with patch("ollama_chat_lib.web_crawler.requests.get", return_value=mock_resp):
            with patch("ollama_chat_lib.web_crawler.extract_text_from_pdf", return_value="PDF text"):
                crawler.crawl()
        assert len(crawler.articles) == 1
        assert crawler.articles[0]["text"] == "PDF text"

    def test_crawl_with_stop_generation_plugin(self, reset_globals):
        """Plugin can stop crawl via stop_generation hook."""
        class StopPlugin:
            def stop_generation(self):
                return True

        crawler = oc.SimpleWebCrawler(
            ["http://a.com", "http://b.com"],
            plugins=[StopPlugin()],
            verbose=False,
        )
        crawler.crawl()
        assert len(crawler.articles) == 0


class TestSimpleWebScraper:

    def test_init_defaults(self):
        scraper = oc.SimpleWebScraper("http://example.com")
        assert scraper.base_url == "http://example.com"
        assert scraper.restrict_to_base is True
        assert "html" in scraper.file_types

    def test_normalize_url_strips_fragment(self):
        scraper = oc.SimpleWebScraper("http://example.com")
        result = scraper._normalize_url("http://example.com/page#section")
        assert "#" not in result

    def test_is_same_domain(self):
        scraper = oc.SimpleWebScraper("http://example.com")
        assert scraper._is_same_domain("http://example.com/page") is True
        assert scraper._is_same_domain("http://other.com/page") is False

    def test_is_allowed_file_type(self):
        scraper = oc.SimpleWebScraper("http://example.com", file_types=["html", "css"])
        assert scraper._is_allowed_file_type("http://example.com/style.css") is True
        assert scraper._is_allowed_file_type("http://example.com/app.exe") is False

    def test_has_extension(self):
        scraper = oc.SimpleWebScraper("http://example.com")
        assert scraper._has_extension("http://example.com/file.html") is True
        assert scraper._has_extension("http://example.com/path/") is False

    def test_get_local_path(self):
        scraper = oc.SimpleWebScraper("http://example.com", output_dir="/out")
        path = scraper._get_local_path("http://example.com/page.html")
        assert path.endswith("page.html")
        assert "/out/" in path

    def test_get_local_path_index(self):
        scraper = oc.SimpleWebScraper("http://example.com", output_dir="/out")
        path = scraper._get_local_path("http://example.com/folder/")
        assert path.endswith("index.html")

    def test_get_local_path_markdown(self):
        scraper = oc.SimpleWebScraper("http://example.com", output_dir="/out")
        path = scraper._get_local_path("http://example.com/page.html", markdown=True)
        assert path.endswith("page.md")
