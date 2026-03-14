"""Tests for document type detection helpers and text extraction."""
import os
import re
import pytest
from unittest.mock import patch, mock_open, MagicMock
from ollama_chat import (
    is_html, is_markdown, is_docx, is_pptx,
    extract_text_from_html, extract_text_from_csv,
)


# ── is_html ──────────────────────────────────────────────────────────────────

class TestIsHtml:

    def test_html_extension(self, tmp_path):
        p = tmp_path / "page.html"
        p.write_text("<html></html>")
        assert is_html(str(p)) is True

    def test_htm_extension(self, tmp_path):
        p = tmp_path / "page.htm"
        p.write_text("")
        assert is_html(str(p)) is True

    def test_xhtml_extension(self, tmp_path):
        p = tmp_path / "page.xhtml"
        p.write_text("")
        assert is_html(str(p)) is True

    def test_non_html_extension_with_html_content(self, tmp_path):
        p = tmp_path / "page.txt"
        p.write_text("<!doctype html>\n<html></html>")
        assert is_html(str(p)) is True

    def test_non_html_extension_without_html_content(self, tmp_path):
        p = tmp_path / "data.txt"
        p.write_text("Just some text")
        assert is_html(str(p)) is False

    def test_nonexistent_file(self):
        assert is_html("/nonexistent/file.txt") is False


# ── is_markdown ──────────────────────────────────────────────────────────────

class TestIsMarkdown:

    def test_md_extension(self, tmp_path):
        p = tmp_path / "doc.md"
        p.write_text("# Hello")
        assert is_markdown(str(p)) is True

    def test_txt_with_heading(self, tmp_path):
        p = tmp_path / "doc.txt"
        p.write_text("# A heading\nSome text")
        assert is_markdown(str(p)) is True

    def test_txt_without_heading(self, tmp_path):
        p = tmp_path / "doc.txt"
        p.write_text("No markdown here")
        assert is_markdown(str(p)) is False

    def test_other_extension(self, tmp_path):
        p = tmp_path / "data.csv"
        p.write_text("# This looks like a heading")
        assert is_markdown(str(p)) is False

    def test_nonexistent_raises(self):
        with pytest.raises(FileNotFoundError):
            is_markdown("/nonexistent/missing.md")


# ── is_docx / is_pptx ───────────────────────────────────────────────────────

class TestIsDocxPptx:

    def test_docx_extension(self):
        assert is_docx("file.docx") is True
        assert is_docx("file.DOCX") is True

    def test_non_docx(self):
        assert is_docx("file.pdf") is False

    def test_pptx_extension(self):
        assert is_pptx("file.pptx") is True
        assert is_pptx("FILE.PPTX") is True

    def test_non_pptx(self):
        assert is_pptx("file.pdf") is False


# ── extract_text_from_html ───────────────────────────────────────────────────

class TestExtractTextFromHtml:

    def test_basic_content(self):
        html = "<html><body><p>Hello world</p></body></html>"
        result = extract_text_from_html(html)
        assert "Hello world" in result

    def test_scripts_removed(self):
        html = "<html><body><script>alert('x')</script><p>Safe</p></body></html>"
        result = extract_text_from_html(html)
        assert "alert" not in result
        assert "Safe" in result

    def test_style_removed(self):
        html = "<html><body><style>.x{color:red}</style><p>Visible</p></body></html>"
        result = extract_text_from_html(html)
        assert "color" not in result
        assert "Visible" in result

    def test_nav_elements_removed(self):
        html = "<html><body><nav>Menu</nav><main><p>Main content</p></main></body></html>"
        result = extract_text_from_html(html)
        assert "Menu" not in result
        assert "Main content" in result

    def test_extra_newlines_collapsed(self):
        html = "<html><body><p>A</p><br><br><br><p>B</p></body></html>"
        result = extract_text_from_html(html)
        assert "\n\n\n" not in result

    def test_empty_html(self):
        result = extract_text_from_html("")
        assert result == "" or result.strip() == ""


# ── extract_text_from_csv ────────────────────────────────────────────────────

class TestExtractTextFromCsv:

    def test_basic_csv(self, tmp_path):
        csv_file = tmp_path / "data.csv"
        csv_file.write_text("Name,Age\nAlice,30\nBob,25\n")
        result = extract_text_from_csv(str(csv_file))
        assert "| Name | Age |" in result
        assert "| Alice | 30 |" in result
        assert "| Bob | 25 |" in result

    def test_empty_csv(self, tmp_path):
        csv_file = tmp_path / "empty.csv"
        csv_file.write_text("")
        result = extract_text_from_csv(str(csv_file))
        assert "empty" in result.lower()

    def test_csv_title_from_filename(self, tmp_path):
        csv_file = tmp_path / "my_report.csv"
        csv_file.write_text("Col1\nVal1\n")
        result = extract_text_from_csv(str(csv_file))
        assert "# my report" in result

    def test_csv_with_semicolon_delimiter(self, tmp_path):
        csv_file = tmp_path / "semi.csv"
        csv_file.write_text("A;B\n1;2\n3;4\n")
        result = extract_text_from_csv(str(csv_file))
        assert "| A | B |" in result
        assert "| 1 | 2 |" in result
