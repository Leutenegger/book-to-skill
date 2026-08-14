from __future__ import annotations
import html
import html.parser
from book_to_skill.parsers.text import read_text_file

class _HTMLTextExtractor(html.parser.HTMLParser):
    SKIP_TAGS = {'script', 'style', 'head'}
    BLOCK_TAGS = frozenset({'address', 'article', 'aside', 'blockquote', 'br', 'dd', 'details', 'div', 'dl', 'dt', 'fieldset', 'figcaption', 'figure', 'footer', 'form', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'header', 'hgroup', 'hr', 'li', 'main', 'nav', 'ol', 'p', 'pre', 'section', 'table', 'tbody', 'tfoot', 'thead', 'tr', 'ul'})
    CELL_TAGS = frozenset({'td', 'th'})

    def __init__(self):
        super().__init__()
        self._parts: list[str] = []
        self._skip_depth = 0
        self._pending = ''

    def _mark(self, separator: str) -> None:
        if separator == '\n' or not self._pending:
            self._pending = separator

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP_TAGS:
            self._skip_depth += 1
        if tag in self.BLOCK_TAGS:
            self._mark('\n')
        elif tag in self.CELL_TAGS:
            self._mark('\t')

    def handle_endtag(self, tag):
        if tag in self.SKIP_TAGS:
            if self._skip_depth:
                self._skip_depth -= 1
            return
        if tag in self.BLOCK_TAGS:
            self._mark('\n')
        elif tag in self.CELL_TAGS:
            self._mark('\t')

    def handle_data(self, data):
        if self._skip_depth:
            return
        if self._pending:
            if not data.strip():
                return
            if self._parts:
                self._parts.append(self._pending)
            self._pending = ''
        self._parts.append(data)

    def get_text(self) -> str:
        return ''.join(self._parts)

def extract_html_content(raw_html: str) -> str:
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(raw_html, 'html.parser')
        for element in soup(['script', 'style', 'head']):
            element.decompose()
        return soup.get_text(separator='\n')
    except ImportError:
        parser = _HTMLTextExtractor()
        parser.feed(raw_html)
        return parser.get_text()

def extract_html_file(path: str) -> str | None:
    raw = read_text_file(path)
    if raw is None:
        return None
    return extract_html_content(raw)
