"""Markdown and tabular-data splitters for document chunking."""

import re


class TabularDataSplitter:
    """
    Splits Markdown-formatted tabular data (from CSV or XLSX) into chunks of rows,
    repeating the header line and separator at the top of each chunk.
    This preserves column semantics so that each chunk is self-contained.
    """
    def __init__(self, markdown_content, rows_per_chunk=50):
        self.markdown_content = markdown_content
        self.rows_per_chunk = rows_per_chunk

    def split(self):
        lines = self.markdown_content.splitlines()
        chunks = []
        # We may have multiple tables (e.g. multi-sheet XLSX with headings).
        # Walk through the lines, detect table header + separator pairs, and
        # chunk the data rows that follow each table.
        i = 0
        preamble = []  # Non-table lines before a table (headings, blank lines)

        while i < len(lines):
            line = lines[i]

            # Detect a Markdown table header: a line starting with '|' followed
            # by a separator line like '| --- | --- |'
            if line.startswith('|') and i + 1 < len(lines) and re.match(r'^\|\s*-{3,}', lines[i + 1]):
                header_line = lines[i]
                separator_line = lines[i + 1]
                i += 2  # move past header + separator

                # Collect all data rows for this table
                data_rows = []
                while i < len(lines) and lines[i].startswith('|'):
                    data_rows.append(lines[i])
                    i += 1

                # Split data rows into chunks
                if not data_rows:
                    # Table with header only
                    chunk_text = '\n'.join(preamble + [header_line, separator_line])
                    chunks.append(chunk_text.strip())
                else:
                    for start in range(0, len(data_rows), self.rows_per_chunk):
                        batch = data_rows[start:start + self.rows_per_chunk]
                        chunk_lines = preamble + [header_line, separator_line] + batch
                        chunks.append('\n'.join(chunk_lines).strip())

                # Reset preamble after consuming a table
                preamble = []
            else:
                # Non-table line (heading, blank, etc.) — accumulate as preamble
                preamble.append(line)
                i += 1

        # If there are trailing non-table lines, add them as a chunk
        if preamble:
            text = '\n'.join(preamble).strip()
            if text:
                chunks.append(text)

        return chunks


class MarkdownSplitter:
    def __init__(self, markdown_content, split_paragraphs=False):
        self.markdown_content = markdown_content.splitlines()
        self.sections = []
        self.split_paragraphs = split_paragraphs  # New parameter to control paragraph splitting
    
    def is_heading(self, line):
        """Returns the heading level if the line is a heading, otherwise returns None."""
        match = re.match(r'^(#{1,4})\s', line)
        return len(match.group(1)) if match else None

    def split(self):
        current_hierarchy = []  # Stores the current heading hierarchy
        current_paragraph = []

        i = 0
        while i < len(self.markdown_content):
            line = self.markdown_content[i].strip()  # Remove leading/trailing whitespace
            
            if not line:  # Empty line found
                if self.split_paragraphs:  # Only handle splitting when split_paragraphs is True
                    # Check the next non-empty line
                    next_non_empty_line = None
                    for j in range(i + 1, len(self.markdown_content)):
                        if self.markdown_content[j].strip():  # Find the next non-empty line
                            next_non_empty_line = self.markdown_content[j].strip()
                            break
                    
                    # If the next non-empty line is a heading or not starting with '#', split paragraph
                    if next_non_empty_line and (self.is_heading(next_non_empty_line) or not next_non_empty_line.startswith('#')) and len(current_paragraph) > 0:
                        # Add the paragraph with the current hierarchy
                        self.sections.append("\n".join(current_hierarchy + ["\n".join(current_paragraph)]))
                        current_paragraph = []  # Reset for the next paragraph

                i += 1
                continue
            
            heading_level = self.is_heading(line)
            
            if heading_level:
                # If we encounter a heading, finalize the current paragraph
                if current_paragraph:
                    # Add the paragraph with the current hierarchy
                    self.sections.append("\n".join(current_hierarchy + ["\n".join(current_paragraph)]))
                    current_paragraph = []

                # Adjust the hierarchy based on the heading level
                # Keep only the parts of the hierarchy up to the current heading level
                current_hierarchy = current_hierarchy[:heading_level - 1] + [line]
            else:
                # Regular content: append the line to the current paragraph
                current_paragraph.append(line)

            i += 1

        # Finalize the last paragraph if present
        if current_paragraph:
            self.sections.append("\n".join(current_hierarchy + ["\n".join(current_paragraph)]))

        return self.sections
