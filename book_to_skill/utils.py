from __future__ import annotations
import glob
import json
import os
import re
import sys
import shutil
import zipfile
from pathlib import Path
from book_to_skill.exceptions import ExtractionError
from book_to_skill.config import OUTPUT_DIR, OUTPUT_TEXT, OUTPUT_META, WORDS_PER_TOKEN, CJK_CHARS_PER_TOKEN, SUPPORTED_EXTENSIONS, TEXT_EXTENSIONS, HTML_EXTENSIONS, CALIBRE_EBOOK_EXTENSIONS, supported_formats_message
from book_to_skill.dependencies import normalize_install_mode, prepare_dependencies, run_dependency_check
from book_to_skill.parsers.text import read_text_file
from book_to_skill.parsers.html import extract_html_file
from book_to_skill.parsers.docx import extract_docx
from book_to_skill.parsers.rtf import extract_rtf
from book_to_skill.parsers.calibre import extract_with_ebook_convert
from book_to_skill.parsers.pdf import extract_with_docling, extract_with_pdftotext, extract_with_pypdf, extract_with_pdfminer, looks_image_only, count_pages
from book_to_skill.parsers.epub import extract_with_ebooklib, extract_with_zipfile, count_epub_chapters
from book_to_skill.sanitize import sanitize_extracted_text
_CJK_RE = re.compile('[\u3000-〿\u3040-ヿ㐀-䶿一-鿿가-힣豈-\ufaff\uff00-\uffef\\U00020000-\\U0003FFFF]')

def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    cjk = len(_CJK_RE.findall(text))
    if not cjk:
        return int(len(text.split()) / WORDS_PER_TOKEN)
    latin_words = len(_CJK_RE.sub(' ', text).split())
    return int(latin_words / WORDS_PER_TOKEN + cjk / CJK_CHARS_PER_TOKEN)
_EXPLICIT_CHAPTER = re.compile('^\\s*(?:chapter|chapitre|kapitel|cap[ií]tulo|capitolo|hoofdstuk|ch\\.?)\\s*(?:(\\d{1,2})|(?P<roman>[IVXLCDMivxlcdm]{1,7}))\\b(?P<rest>.*)$', re.IGNORECASE)
_HEADING_TAIL = re.compile('^\\s*$|^\\s*[.:\\-—–]|^\\s+[A-ZÀ-Þ0-9\\"“(]')
_ROMAN_HEAD = re.compile('^\\s*([IVXLCDM]+)\\s*[:.]\\s+[A-ZÀ-Þ0-9\\"“(]')
_LC_MD_ROMAN = re.compile('^\\s*#{1,6}\\s+([ivxlcdm]+)\\s*[:.]\\s+[A-Za-zÀ-Þ\\"“(]')
_ROMAN_VALUES = {'I': 1, 'V': 5, 'X': 10, 'L': 50, 'C': 100, 'D': 500, 'M': 1000}
_MD_HEADING_PREFIX = re.compile('^(#{1,6}|={1,6})\\s+')
_CN_NUM_VALUES = {'〇': 0, '零': 0, '一': 1, '二': 2, '两': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9}
_CN_NUM_UNITS = {'十': 10, '百': 100, '千': 1000}
_CN_NUM_CLASS = '〇零一二两三四五六七八九十百千'
_FW_DIGITS = '０-９'
_CN_CHAPTER = re.compile(f'^\\s*第\\s*([0-9{_FW_DIGITS}{_CN_NUM_CLASS}]+)\\s*[章回卷节篇讲]')
_MD_CN_HEADING = re.compile(f'^#{{1,6}}\\s+第?\\s*([{_FW_DIGITS}{_CN_NUM_CLASS}]+)\\s*[·、.:：章回卷节篇讲]')
_TH_DIGITS = '๐-๙'
_TH_DIGIT_MAP = str.maketrans('๐๑๒๓๔๕๖๗๘๙', '0123456789')
_TH_CHAPTER = re.compile(f'^\\s*(?:#{{1,6}}\\s+)?(?:บทที่|ตอนที่|ภาคที่|บท|ตอน|ภาค)\\s*([0-9{_TH_DIGITS}]+)\\b')
_KO_CHAPTER = re.compile('^\\s*(?:#{1,6}\\s+)?제\\s*([0-9]+)\\s*[장편절관](?:\\s*의\\s*[0-9]+)?(?:\\s*$|[.:\\-]|\\s+\\S)')
_TOC_HEADERS = ('table of contents', 'contents', 'índice', 'sumário', 'sumario', 'table des matières', 'inhaltsverzeichnis', 'indice', 'sommario', 'inhoudsopgave')
_TOC_CJK_PATTERN = '目[ \\t\\u3000]*(?:录|錄|次)'
_TOC_PATTERN = re.compile('^\\s*(?:' + '|'.join([*(re.escape(h) for h in _TOC_HEADERS), _TOC_CJK_PATTERN]) + ')\\s*$', re.IGNORECASE | re.MULTILINE)
_ATX_HEADING = re.compile('^(#{1,6}|={1,6})\\s+(.+?)\\s*#*$')
_SETEXT_UNDERLINE = re.compile('^(={2,}|-{2,})$')
_CODE_FENCE = re.compile('^(`{3,}|~{3,})')

def _closed_fence_line_numbers(lines: list[str]) -> set[int]:
    inside: set[int] = set()
    opener: tuple[str, int] | None = None
    for index, line in enumerate(lines):
        match = _CODE_FENCE.match(line.strip())
        if not match:
            continue
        marker = match.group(1)
        if opener is None:
            opener = (marker[0], index)
        elif marker[0] == opener[0]:
            inside.update(range(opener[1], index + 1))
            opener = None
    return inside

def _structural_chapter_count(text: str) -> int:
    levels: dict[int, set[str]] = {}
    lines = text.splitlines()
    fenced = _closed_fence_line_numbers(lines)
    prev = ''
    for index, line in enumerate(lines):
        if index in fenced:
            prev = ''
            continue
        s = line.strip()
        if _SETEXT_UNDERLINE.match(s) and prev and (not _SETEXT_UNDERLINE.match(prev)) and (len(s) >= len(prev)):
            depth = 1 if s[0] == '=' else 2
            levels.setdefault(depth, set()).add(prev.lower())
            prev = ''
            continue
        m = _ATX_HEADING.match(s)
        if m:
            title = m.group(2).strip().lower()
            if title and (not title[0].isdigit()) and re.search('\\w', title):
                levels.setdefault(len(m.group(1)), set()).add(title)
            prev = ''
            continue
        prev = s
    if not levels:
        return 0
    for depth in sorted(levels):
        if len(levels[depth]) >= 2:
            return len(levels[depth])
    return sum((len(titles) for titles in levels.values()))

def _cn_numeral_to_int(s: str) -> int | None:
    if s.isdigit():
        n = int(s)
        return n if 1 <= n <= 999 else None
    section = current = 0
    for ch in s:
        if ch in _CN_NUM_VALUES:
            current = _CN_NUM_VALUES[ch]
        elif ch in _CN_NUM_UNITS:
            section += (current or 1) * _CN_NUM_UNITS[ch]
            current = 0
        else:
            return None
    total = section + current
    return total if 1 <= total <= 999 else None

def _int_to_roman(n: int) -> str:
    table = [(1000, 'M'), (900, 'CM'), (500, 'D'), (400, 'CD'), (100, 'C'), (90, 'XC'), (50, 'L'), (40, 'XL'), (10, 'X'), (9, 'IX'), (5, 'V'), (4, 'IV'), (1, 'I')]
    out = []
    for val, sym in table:
        while n >= val:
            out.append(sym)
            n -= val
    return ''.join(out)

def _roman_to_int(s: str) -> int | None:
    s = s.upper()
    total = prev = 0
    for ch in reversed(s):
        v = _ROMAN_VALUES.get(ch)
        if v is None:
            return None
        total += -v if v < prev else v
        prev = max(prev, v)
    if total == 0 or total > 200:
        return None
    return total if _int_to_roman(total) == s else None

def _match_chapter_number(line: str) -> int | None:
    s = line.strip()
    if len(s) > 80:
        return None
    m = _EXPLICIT_CHAPTER.match(s)
    if m and _HEADING_TAIL.match(m.group('rest')):
        if m.group(1):
            return int(m.group(1))
        return _roman_to_int(m.group('roman').upper())
    rm = _ROMAN_HEAD.match(s) or _LC_MD_ROMAN.match(s)
    if rm:
        return _roman_to_int(rm.group(1))
    cm = _CN_CHAPTER.match(s) or _MD_CN_HEADING.match(s)
    if cm:
        return _cn_numeral_to_int(cm.group(1))
    tm = _TH_CHAPTER.match(s)
    if tm:
        return int(tm.group(1).translate(_TH_DIGIT_MAP))
    km = _KO_CHAPTER.match(s)
    if km:
        return int(km.group(1))
    return None

def _chapter_number(line: str) -> int | None:
    match = _match_chapter_number(line)
    if match is not None:
        return match
    s = line.strip()
    md = _MD_HEADING_PREFIX.match(s)
    if md:
        return _match_chapter_number(s[md.end():])
    return None

def detect_structure(text: str) -> dict:
    lines = text.splitlines()
    headings = []
    numbers = set()
    for line in lines:
        num = _chapter_number(line)
        if num is not None:
            numbers.add(num)
            headings.append(line.strip())
    numeric_count = len(numbers)
    chapters_detected = numeric_count if numeric_count > 0 else _structural_chapter_count(text)
    has_toc = bool(_TOC_PATTERN.search(text[:30000]))
    return {'chapters_detected': chapters_detected, 'chapter_headings_sample': headings[:10], 'has_toc': has_toc}

def parse_arguments(argv: list[str]) -> tuple[list[str], str, str]:
    input_paths = []
    extraction_mode = 'text'
    args = argv[1:]
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == '--mode':
            if i + 1 < len(args):
                extraction_mode = args[i + 1].lower()
                i += 2
            else:
                i += 1
        elif arg == '--install-missing':
            if i + 1 < len(args) and (not args[i + 1].startswith('--')):
                i += 2
            else:
                i += 1
        elif arg == '--no-install-missing':
            i += 1
        elif arg.startswith('-'):
            print(f"WARNING: Unknown flag '{arg}' — ignoring it.", file=sys.stderr)
            i += 1
        else:
            input_paths.append(arg)
            i += 1
    install_mode = normalize_install_mode(argv)
    if extraction_mode not in ('technical', 'text'):
        extraction_mode = 'text'
    return (input_paths, extraction_mode, install_mode)

def resolve_input_files(paths: list[str]) -> list[Path]:
    resolved = []
    for raw_path in paths:
        path_str = os.path.expanduser(raw_path)
        looks_like_glob = any((char in path_str for char in ('*', '?', '[')))
        if looks_like_glob and not Path(path_str).exists():
            glob_matches = glob.glob(path_str, recursive=True)
            expanded = []
            for match in glob_matches:
                p = Path(match)
                if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS:
                    expanded.append(p.resolve())
            expanded.sort(key=lambda x: str(x).lower())
            resolved.extend(expanded)
        else:
            p = Path(path_str)
            if p.is_dir():
                dir_files = []
                for root, _, files in os.walk(p):
                    for file in files:
                        file_path = Path(root) / file
                        if file_path.suffix.lower() in SUPPORTED_EXTENSIONS:
                            dir_files.append(file_path.resolve())
                dir_files.sort(key=lambda x: str(x).lower())
                resolved.extend(dir_files)
            else:
                resolved.append(p.resolve())
    seen = set()
    unique_paths = []
    for path in resolved:
        resolved_path = path.resolve() if path.exists() else path
        if resolved_path not in seen:
            seen.add(resolved_path)
            unique_paths.append(resolved_path)
    return unique_paths

def extract_single_file(input_path: Path, extraction_mode: str, install_mode: str) -> dict:
    input_str = str(input_path)
    if not input_path.exists():
        raise ExtractionError(f'File not found: {input_str}')
    ext = input_path.suffix.lower()
    document_format = ext.lstrip('.')
    if ext not in SUPPORTED_EXTENSIONS:
        try:
            with open(input_str, 'rb') as f:
                header = f.read(8)
        except OSError as exc:
            raise ExtractionError(f'Could not read {input_path.name}: {exc.strerror or exc}') from exc
        if header[:4] == b'%PDF':
            ext = '.pdf'
            document_format = 'pdf'
        elif header[:2] == b'PK':
            try:
                with zipfile.ZipFile(input_str) as zf:
                    names = set(zf.namelist())
                    if 'mimetype' in names and zf.read('mimetype').startswith(b'application/epub'):
                        ext = '.epub'
                        document_format = 'epub'
                    elif 'word/document.xml' in names:
                        ext = '.docx'
                        document_format = 'docx'
                    else:
                        raise ExtractionError(f"Unsupported ZIP-based format '{input_path.name}'. Supported: {supported_formats_message()}")
            except (zipfile.BadZipFile, KeyError, OSError):
                raise ExtractionError(f"Unsupported ZIP-based format '{input_path.name}'. Supported: {supported_formats_message()}")
        else:
            raise ExtractionError(f"Unsupported format '{ext or '<none>'}'. Supported: {supported_formats_message()}")
    prepare_dependencies(ext, extraction_mode, install_mode)
    if ext in CALIBRE_EBOOK_EXTENSIONS and (not shutil.which('ebook-convert')):
        raise ExtractionError("MOBI/AZW/AZW3 extraction requires Calibre's ebook-convert command. Install Calibre and ensure ebook-convert is on PATH, then rerun this command.")
    text = ''
    method = ''
    pages = 0
    pages_label = 'sections'
    if ext == '.epub':
        print(f'Extracting EPUB: {input_str}')
        text = extract_with_ebooklib(input_str)
        if text and text.strip():
            method = 'ebooklib'
        else:
            print('ebooklib not available')
            print('Trying stdlib zipfile parser...', end=' ', flush=True)
            text = extract_with_zipfile(input_str)
            if text and text.strip():
                print('OK')
                method = 'zipfile'
            else:
                print('FAILED')
                raise ExtractionError('Could not extract text from EPUB.\nInstall ebooklib + beautifulsoup4 for best results:\n  pip3 install ebooklib beautifulsoup4')
        pages = count_epub_chapters(input_str)
        pages_label = 'spine_items'
    elif ext == '.pdf':
        print(f'Extracting PDF: {input_str}')
        if looks_image_only(input_str):
            raise ExtractionError(f'{input_path.name} looks like a scanned (image-only) PDF: its first pages contain no extractable text, only images.\nRun OCR on it first, then retry:\n  ocrmypdf input.pdf output.pdf')
        if extraction_mode == 'technical':
            print('Mode: technical — using Docling (layout-aware)...', end=' ', flush=True)
            text = extract_with_docling(input_str)
            if text and text.strip():
                method = 'docling'
                print('OK')
            else:
                print('not available, falling back to pdftotext')
                extraction_mode = 'text'
        if extraction_mode == 'text' or not text:
            print('Mode: text — using pdftotext...')
            print('Trying pdftotext...', end=' ', flush=True)
            text = extract_with_pdftotext(input_str)
            if text and text.strip():
                method = 'pdftotext'
                print('OK')
            else:
                print('not available')
                print('Trying pypdf...', end=' ', flush=True)
                text = extract_with_pypdf(input_str)
                if text and text.strip():
                    method = 'pypdf'
                    print('OK')
                else:
                    print('not available')
                    print('Trying pdfminer.six...', end=' ', flush=True)
                    text = extract_with_pdfminer(input_str)
                    if text and text.strip():
                        method = 'pdfminer'
                        print('OK')
                    else:
                        print('FAILED')
                        raise ExtractionError('Could not extract text from PDF.\nInstall one of: poppler-utils (pdftotext), pypdf, or pdfminer.six\n  sudo apt install poppler-utils\n  pip3 install pypdf\n  pip3 install pdfminer.six')
        pages = count_pages(input_str)
        pages_label = 'pages'
    elif ext in TEXT_EXTENSIONS:
        print(f'Extracting text document: {input_str}')
        text = read_text_file(input_str)
        if text is None or not text.strip():
            raise ExtractionError(f'Could not read text document: {input_path.name}')
        method = 'plain-text'
        pages = 0
        pages_label = 'sections'
    elif ext in HTML_EXTENSIONS:
        print(f'Extracting HTML: {input_str}')
        text = extract_html_file(input_str)
        if text is None or not text.strip():
            raise ExtractionError(f'Could not extract text from HTML: {input_path.name}')
        method = 'html-parser'
        pages = 0
        pages_label = 'sections'
    elif ext == '.docx':
        print(f'Extracting DOCX: {input_str}')
        text, method = extract_docx(input_str)
        pages = 0
        pages_label = 'sections'
    elif ext == '.rtf':
        print(f'Extracting RTF: {input_str}')
        text, method = extract_rtf(input_str)
        pages = 0
        pages_label = 'sections'
    elif ext in CALIBRE_EBOOK_EXTENSIONS:
        print(f'Extracting ebook with Calibre: {input_str}')
        text = extract_with_ebook_convert(input_str)
        if text is None or not text.strip():
            raise ExtractionError(f'Could not extract text from {ext}. Install Calibre and ensure ebook-convert is on PATH.')
        method = 'ebook-convert'
        pages = 0
        pages_label = 'sections'
    text, removed_invisible = sanitize_extracted_text(text)
    if removed_invisible:
        print(f'  [security] removed {removed_invisible} invisible Unicode code point(s) from {input_path.name}', file=sys.stderr)
    if not text.strip():
        raise ExtractionError(f'Extracted text from {input_path.name} contained no visible content after Unicode sanitization.')
    tokens = estimate_tokens(text)
    structure = detect_structure(text)
    file_size_mb = os.path.getsize(input_str) / (1024 * 1024)
    return {'source_file': str(input_path.resolve()), 'filename': input_path.name, 'format': document_format, 'extraction_method': method, 'file_size_mb': round(file_size_mb, 2), pages_label: pages, 'pages_label': pages_label, 'pages': pages, 'chars': len(text), 'words': len(text.split()), 'estimated_tokens': tokens, 'text': text, **structure}

def prepare_output_dir(path: Path) -> None:
    if path.is_symlink():
        raise ExtractionError(f'Refusing to use {path}: it is a symbolic link, not a real directory. Remove it or set BOOK_SKILL_WORKDIR to a private path.')
    if path.exists():
        if not path.is_dir():
            raise ExtractionError(f'Refusing to use {path}: it exists and is not a directory.')
        if hasattr(os, 'getuid'):
            owner_uid = path.stat().st_uid
            if owner_uid != os.getuid():
                raise ExtractionError(f'Refusing to use {path}: it is owned by a different user (uid {owner_uid}). Set BOOK_SKILL_WORKDIR to a private directory.')
            os.chmod(path, 448)
    else:
        path.mkdir(parents=True, mode=448)

def print_banner() -> None:
    banner = Path(__file__).resolve().parent.parent / 'scripts' / 'banner.txt'
    try:
        sys.stderr.write(banner.read_text(encoding='utf-8') + '\n')
    except Exception:
        pass

def print_usage() -> None:
    print('Usage: book-to-skill <path-to-document-folder-or-glob>... [--mode technical|text] [--install-missing ask|yes|no]', file=sys.stderr)
    print('       book-to-skill --check    # report which extractors are installed', file=sys.stderr)
    print(f'Supported formats: {supported_formats_message()}', file=sys.stderr)

def main():
    print_banner()
    if any((arg in {'-h', '--help'} for arg in sys.argv[1:])):
        print_usage()
        sys.exit(0)
    if '--check' in sys.argv[1:]:
        sys.exit(run_dependency_check())
    if len(sys.argv) < 2:
        print_usage()
        sys.exit(1)
    raw_input_paths, extraction_mode, install_mode = parse_arguments(sys.argv)
    if not raw_input_paths:
        print('ERROR: No input document, folder, or glob pattern specified.', file=sys.stderr)
        sys.exit(1)
    input_files = resolve_input_files(raw_input_paths)
    if not input_files:
        print(f"ERROR: No supported files found matching: {', '.join(raw_input_paths)}", file=sys.stderr)
        sys.exit(1)
    prepare_output_dir(OUTPUT_DIR)
    extracted_sources = []
    combined_texts = []
    errors = []
    for file_path in input_files:
        try:
            res = extract_single_file(file_path, extraction_mode, install_mode)
        except ExtractionError as exc:
            print(f'WARNING: Skipping {file_path.name}: {exc}', file=sys.stderr)
            errors.append((file_path, str(exc)))
            continue
        extracted_sources.append(res)
        separator = f"\n\n{'=' * 80}\nSOURCE: {res['filename']} (Path: {res['source_file']})\n{'=' * 80}\n\n"
        combined_texts.append(separator + res['text'])
    if not extracted_sources:
        print(f'\nERROR: All {len(errors)} source(s) failed extraction:', file=sys.stderr)
        for path, err in errors:
            print(f'  - {path.name}: {err}', file=sys.stderr)
        sys.exit(1)
    consolidated_text = ''.join(combined_texts).strip()
    OUTPUT_TEXT.write_text(consolidated_text, encoding='utf-8')
    total_file_size_mb = sum((src['file_size_mb'] for src in extracted_sources))
    total_pages = sum((src['pages'] for src in extracted_sources))
    total_chars = len(consolidated_text)
    total_words = len(consolidated_text.split())
    total_tokens = estimate_tokens(consolidated_text)
    structure_text = '\n\n'.join((src['text'] for src in extracted_sources))
    consolidated_structure = detect_structure(structure_text)
    consolidated_structure['has_toc'] = any((src['has_toc'] for src in extracted_sources))
    metadata = {'source_file': 'Consolidated from multiple sources' if len(extracted_sources) > 1 else extracted_sources[0]['source_file'], 'filename': 'multi-source' if len(extracted_sources) > 1 else extracted_sources[0]['filename'], 'format': 'mixed' if len(extracted_sources) > 1 else extracted_sources[0]['format'], 'extraction_method': 'multi-method' if len(extracted_sources) > 1 else extracted_sources[0]['extraction_method'], 'extraction_mode': extraction_mode, 'file_size_mb': round(total_file_size_mb, 2), 'pages': total_pages, 'chars': total_chars, 'words': total_words, 'estimated_tokens': total_tokens, 'estimated_tokens_human': f'~{total_tokens // 1000}K', 'output_text': str(OUTPUT_TEXT), 'total_sources': len(extracted_sources), 'sources': [{'source_file': src['source_file'], 'filename': src['filename'], 'format': src['format'], 'extraction_method': src['extraction_method'], 'file_size_mb': src['file_size_mb'], 'pages': src['pages'], 'pages_label': src['pages_label'], 'chars': src['chars'], 'words': src['words'], 'estimated_tokens': src['estimated_tokens'], 'chapters_detected': src['chapters_detected'], 'has_toc': src['has_toc']} for src in extracted_sources], **consolidated_structure}
    OUTPUT_META.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding='utf-8')
    page_line = f'   Total Pages: {total_pages}'
    print('\nExtraction complete:')
    print(f'   Sources : {len(extracted_sources)} processed')
    print(f'   Size    : {total_file_size_mb:.2f} MB')
    print(page_line)
    print(f'   Words   : {total_words:,}')
    print(f'   Tokens  : ~{total_tokens // 1000}K')
    print(f"   Chapters: {consolidated_structure['chapters_detected']} detected overall")
    print(f"   ToC     : {('yes' if consolidated_structure['has_toc'] else 'not detected')}")
    if not consolidated_structure['has_toc']:
        print('   WARN    : No table of contents detected — chapter mapping in Step 3 will rely on heading scan only, which may miss or duplicate sections.')
    print(f'\n   Text -> {OUTPUT_TEXT}')
    print(f'   Meta -> {OUTPUT_META}')
    if errors:
        print(f'\n   WARNING: {len(errors)} source(s) skipped due to errors:')
        for path, err in errors:
            print(f'     - {path.name}: {err}')
