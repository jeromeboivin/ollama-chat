"""Tests for TabularDataSplitter and MarkdownSplitter."""
import pytest
from ollama_chat import TabularDataSplitter, MarkdownSplitter


# ── TabularDataSplitter ─────────────────────────────────────────────────────

class TestTabularDataSplitter:

    def test_basic_table_single_chunk(self):
        md = (
            "# Sales\n"
            "| Name | Amount |\n"
            "| --- | --- |\n"
            "| Alice | 100 |\n"
            "| Bob | 200 |\n"
        )
        chunks = TabularDataSplitter(md, rows_per_chunk=50).split()
        assert len(chunks) == 1
        assert "| Name | Amount |" in chunks[0]
        assert "| Alice | 100 |" in chunks[0]
        assert "| Bob | 200 |" in chunks[0]
        # Preamble heading should be included
        assert "# Sales" in chunks[0]

    def test_chunking_splits_rows(self):
        header = "| H1 | H2 |\n| --- | --- |\n"
        rows = "".join(f"| r{i} | v{i} |\n" for i in range(10))
        md = header + rows
        chunks = TabularDataSplitter(md, rows_per_chunk=3).split()
        # 10 rows / 3 per chunk → 4 chunks (3+3+3+1)
        assert len(chunks) == 4
        # Each chunk must repeat the header
        for chunk in chunks:
            assert "| H1 | H2 |" in chunk
            assert "| --- | --- |" in chunk

    def test_empty_table_header_only(self):
        md = "| A |\n| --- |\n"
        chunks = TabularDataSplitter(md, rows_per_chunk=5).split()
        assert len(chunks) == 1
        assert "| A |" in chunks[0]

    def test_preamble_heading_repeated(self):
        md = (
            "# Report\n"
            "\n"
            "## Sheet1\n"
            "| X |\n"
            "| --- |\n"
            "| 1 |\n"
            "| 2 |\n"
            "| 3 |\n"
            "| 4 |\n"
        )
        chunks = TabularDataSplitter(md, rows_per_chunk=2).split()
        # Should produce 2 chunks (2+2 rows), each with the preamble headings
        assert len(chunks) == 2
        for chunk in chunks:
            assert "# Report" in chunk
            assert "## Sheet1" in chunk

    def test_multi_table_document(self):
        md = (
            "# Doc\n"
            "## Table A\n"
            "| A |\n"
            "| --- |\n"
            "| 1 |\n"
            "\n"
            "## Table B\n"
            "| B |\n"
            "| --- |\n"
            "| 2 |\n"
        )
        chunks = TabularDataSplitter(md, rows_per_chunk=50).split()
        assert len(chunks) == 2
        assert "## Table A" in chunks[0]
        assert "## Table B" in chunks[1]

    def test_trailing_non_table_lines(self):
        md = "Some standalone text\nwithout any table"
        chunks = TabularDataSplitter(md, rows_per_chunk=5).split()
        assert len(chunks) == 1
        assert "Some standalone text" in chunks[0]


# ── MarkdownSplitter ────────────────────────────────────────────────────────

class TestMarkdownSplitter:

    def test_single_section(self):
        md = "# Title\nSome content here."
        sections = MarkdownSplitter(md).split()
        assert len(sections) == 1
        assert "# Title" in sections[0]
        assert "Some content here." in sections[0]

    def test_multiple_h1_sections(self):
        md = "# A\nContent A\n# B\nContent B"
        sections = MarkdownSplitter(md).split()
        assert len(sections) == 2
        assert "Content A" in sections[0]
        assert "Content B" in sections[1]

    def test_nested_headings(self):
        md = "# H1\n## H2\nNested content\n# Another H1\nMore content"
        sections = MarkdownSplitter(md).split()
        assert len(sections) == 2
        # First section should carry both headings
        assert "# H1" in sections[0]
        assert "## H2" in sections[0]
        assert "Nested content" in sections[0]
        assert "More content" in sections[1]

    def test_heading_hierarchy_reset(self):
        md = "# H1\n## H2a\nContent A\n## H2b\nContent B"
        sections = MarkdownSplitter(md).split()
        assert len(sections) == 2
        # H2b section should still have H1 as its parent
        assert "# H1" in sections[1]
        assert "## H2b" in sections[1]

    def test_split_paragraphs_off(self):
        md = "# Title\nPara 1\n\nPara 2"
        sections = MarkdownSplitter(md, split_paragraphs=False).split()
        # With split_paragraphs=False, both paragraphs stay together
        assert len(sections) == 1
        assert "Para 1" in sections[0]
        assert "Para 2" in sections[0]

    def test_split_paragraphs_on(self):
        md = "# Title\nPara 1\n\nPara 2"
        sections = MarkdownSplitter(md, split_paragraphs=True).split()
        assert len(sections) == 2
        assert "Para 1" in sections[0]
        assert "Para 2" in sections[1]

    def test_empty_input(self):
        sections = MarkdownSplitter("").split()
        assert sections == []

    def test_no_headings(self):
        md = "Just plain text without headings."
        sections = MarkdownSplitter(md).split()
        assert len(sections) == 1
        assert "Just plain text" in sections[0]

    def test_heading_levels_beyond_4(self):
        md = "##### H5 level\nContent under H5"
        sections = MarkdownSplitter(md).split()
        # H5+ are not recognized as headings (regex matches only 1-4)
        assert len(sections) == 1
        assert "##### H5 level" in sections[0]
