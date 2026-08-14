import json
import sys
import textwrap
import zipfile
from pathlib import Path
from unittest import mock
import pytest
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))
from book_to_skill.exceptions import ExtractionError
from book_to_skill.utils import resolve_input_files, extract_single_file, parse_arguments, estimate_tokens, detect_structure, _cn_numeral_to_int, main
from book_to_skill.config import SUPPORTED_EXTENSIONS
from book_to_skill.parsers import pdf as pdf_parser
from book_to_skill.parsers.text import read_text_file
from book_to_skill.parsers.docx import extract_docx_with_zipfile
from book_to_skill.parsers.rtf import strip_rtf_fallback
from book_to_skill.parsers.epub import extract_with_zipfile

def _make_text_file(path: Path, content: str='Hello world from test file.') -> Path:
    path.write_text(content, encoding='utf-8')
    return path

def _make_md_file(path: Path, content: str='# Title\n\nSome markdown content.') -> Path:
    path.write_text(content, encoding='utf-8')
    return path

def _make_html_file(path: Path) -> Path:
    path.write_text('<html><body><h1>Hello</h1><p>Test paragraph.</p></body></html>', encoding='utf-8')
    return path

def _make_minimal_epub(path: Path) -> Path:
    with zipfile.ZipFile(path, 'w') as zf:
        zf.writestr('mimetype', 'application/epub+zip')
        zf.writestr('content.opf', textwrap.dedent('                <?xml version="1.0"?>\n                <package xmlns="http://www.idpf.org/2007/opf" version="3.0">\n                  <metadata/>\n                  <manifest>\n                    <item id="ch1" href="chapter1.xhtml" media-type="application/xhtml+xml"/>\n                  </manifest>\n                  <spine>\n                    <itemref idref="ch1"/>\n                  </spine>\n                </package>\n            '))
        zf.writestr('chapter1.xhtml', '<html><body><p>EPUB chapter one content.</p></body></html>')
    return path

def _make_minimal_docx(path: Path) -> Path:
    ns = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
    xml = textwrap.dedent(f'        <?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n        <w:document xmlns:w="{ns}">\n          <w:body>\n            <w:p><w:r><w:t>DOCX test paragraph</w:t></w:r></w:p>\n          </w:body>\n        </w:document>\n    ')
    with zipfile.ZipFile(path, 'w') as zf:
        zf.writestr('word/document.xml', xml)
        zf.writestr('[Content_Types].xml', '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
    return path

def _make_unsupported_file(path: Path) -> Path:
    path.write_bytes(b'unsupported binary junk data')
    return path

def _make_oebps_epub(path: Path) -> Path:
    with zipfile.ZipFile(path, 'w') as zf:
        zf.writestr('mimetype', 'application/epub+zip')
        zf.writestr('META-INF/container.xml', textwrap.dedent('                <?xml version="1.0"?>\n                <container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"\n                           version="1.0">\n                  <rootfiles>\n                    <rootfile full-path="OEBPS/content.opf"\n                              media-type="application/oebps-package+xml"/>\n                  </rootfiles>\n                </container>\n            '))
        zf.writestr('OEBPS/content.opf', textwrap.dedent('                <?xml version="1.0"?>\n                <package xmlns="http://www.idpf.org/2007/opf" version="3.0">\n                  <metadata/>\n                  <manifest>\n                    <item id="ch1" href="sections/ch1.xhtml" media-type="application/xhtml+xml"/>\n                    <item id="ch2" href="sections/ch2.xhtml" media-type="application/xhtml+xml"/>\n                  </manifest>\n                  <spine>\n                    <itemref idref="ch1"/>\n                    <itemref idref="ch2"/>\n                  </spine>\n                </package>\n            '))
        zf.writestr('OEBPS/sections/ch1.xhtml', '<html><body><p>Chapter one from OEBPS.</p></body></html>')
        zf.writestr('OEBPS/sections/ch2.xhtml', '<html><body><p>Chapter two from OEBPS.</p></body></html>')
    return path

class TestEpubExtractionFix:

    def test_epub_extract_with_ebooklib_returns_str_or_none(self):
        from book_to_skill.parsers.epub import extract_with_ebooklib
        result = extract_with_ebooklib('nonexistent.epub')
        assert result is None or isinstance(result, str), f'extract_with_ebooklib should return str|None, got {type(result)}'

    def test_epub_extraction_via_zipfile_fallback(self, tmp_path):
        epub_path = _make_minimal_epub(tmp_path / 'test.epub')
        with mock.patch('book_to_skill.utils.prepare_dependencies'):
            result = extract_single_file(epub_path, 'text', 'no')
        assert result['format'] == 'epub'
        assert result['extraction_method'] in ('ebooklib', 'zipfile')
        assert 'EPUB chapter one content' in result['text']
        assert result['chars'] > 0
        assert result['words'] > 0

    def test_epub_no_tuple_unpack_error(self, tmp_path):
        epub_path = _make_minimal_epub(tmp_path / 'test.epub')
        with mock.patch('book_to_skill.utils.prepare_dependencies'):
            try:
                result = extract_single_file(epub_path, 'text', 'no')
            except (TypeError, ValueError) as exc:
                pytest.fail(f'Tuple-unpack regression! Got: {exc}')
        assert result['text']

class TestEpubOpfRelativePaths:

    def test_zipfile_fallback_resolves_oebps_paths(self, tmp_path):
        from book_to_skill.parsers.epub import extract_with_zipfile
        epub_path = _make_oebps_epub(tmp_path / 'oebps.epub')
        text = extract_with_zipfile(str(epub_path))
        assert text is not None, 'extract_with_zipfile returned None for OEBPS EPUB'
        assert 'Chapter one from OEBPS' in text
        assert 'Chapter two from OEBPS' in text

    def test_full_extraction_with_oebps_epub(self, tmp_path):
        epub_path = _make_oebps_epub(tmp_path / 'test_oebps.epub')
        with mock.patch('book_to_skill.utils.prepare_dependencies'):
            result = extract_single_file(epub_path, 'text', 'no')
        assert result['format'] == 'epub'
        assert result['extraction_method'] in ('ebooklib', 'zipfile')
        assert 'Chapter one from OEBPS' in result['text']
        assert 'Chapter two from OEBPS' in result['text']

    def test_container_xml_locates_opf(self, tmp_path):
        from book_to_skill.parsers.epub import _find_opf_path
        epub_path = _make_oebps_epub(tmp_path / 'container.epub')
        with zipfile.ZipFile(epub_path) as zf:
            opf_path = _find_opf_path(zf)
        assert opf_path == 'OEBPS/content.opf'

    def test_count_chapters_with_oebps(self, tmp_path):
        from book_to_skill.parsers.epub import count_epub_chapters
        epub_path = _make_oebps_epub(tmp_path / 'chapters.epub')
        count = count_epub_chapters(str(epub_path))
        assert count == 2

    def test_root_level_opf_still_works(self, tmp_path):
        from book_to_skill.parsers.epub import extract_with_zipfile
        epub_path = _make_minimal_epub(tmp_path / 'root_opf.epub')
        text = extract_with_zipfile(str(epub_path))
        assert text is not None
        assert 'EPUB chapter one content' in text

class TestBatchResilience:

    def test_extract_single_file_raises_on_missing(self, tmp_path):
        missing = tmp_path / 'does_not_exist.txt'
        with pytest.raises(ExtractionError, match='File not found'):
            extract_single_file(missing, 'text', 'no')

    def test_extract_single_file_raises_on_unsupported(self, tmp_path):
        unsupported = _make_unsupported_file(tmp_path / 'data.xyz')
        with pytest.raises(ExtractionError, match='Unsupported format'):
            extract_single_file(unsupported, 'text', 'no')

    def test_batch_continues_past_bad_files(self, tmp_path):
        good_file = _make_text_file(tmp_path / 'good.txt', 'Good content here.')
        bad_file = _make_unsupported_file(tmp_path / 'bad.xyz')
        input_files = [good_file, bad_file]
        extracted = []
        errors = []
        for fp in input_files:
            try:
                with mock.patch('book_to_skill.utils.prepare_dependencies'):
                    res = extract_single_file(fp, 'text', 'no')
                extracted.append(res)
            except ExtractionError as exc:
                errors.append((fp, str(exc)))
        assert len(extracted) == 1, 'Good file should have been extracted'
        assert len(errors) == 1, 'Bad file should have been recorded as error'
        assert 'Good content here' in extracted[0]['text']

    def test_batch_fails_hard_when_all_fail(self, tmp_path, monkeypatch):
        bad1 = _make_unsupported_file(tmp_path / 'bad1.xyz')
        bad2 = _make_unsupported_file(tmp_path / 'bad2.abc')
        monkeypatch.setattr('sys.argv', ['extract.py', str(bad1), str(bad2), '--install-missing', 'no'])
        monkeypatch.setattr('book_to_skill.utils.prepare_dependencies', lambda *a: None)
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1

    def test_main_produces_output_with_partial_failures(self, tmp_path, monkeypatch):
        good = _make_text_file(tmp_path / 'good.txt', 'Partial success content.')
        bad = _make_unsupported_file(tmp_path / 'bad.xyz')
        out_dir = tmp_path / 'output'
        monkeypatch.setenv('BOOK_SKILL_WORKDIR', str(out_dir))
        monkeypatch.setattr('sys.argv', ['extract.py', str(good), str(bad), '--install-missing', 'no'])
        out_text = out_dir / 'full_text.txt'
        out_meta = out_dir / 'metadata.json'
        monkeypatch.setattr('book_to_skill.utils.OUTPUT_DIR', out_dir)
        monkeypatch.setattr('book_to_skill.utils.OUTPUT_TEXT', out_text)
        monkeypatch.setattr('book_to_skill.utils.OUTPUT_META', out_meta)
        monkeypatch.setattr('book_to_skill.utils.prepare_dependencies', lambda *a: None)
        main()
        assert out_text.exists(), 'full_text.txt should be created'
        assert out_meta.exists(), 'metadata.json should be created'
        text = out_text.read_text(encoding='utf-8')
        assert 'Partial success content' in text
        meta = json.loads(out_meta.read_text(encoding='utf-8'))
        assert meta['total_sources'] == 1

    @pytest.mark.parametrize('reported_source', ['/x/sample.md', '/deep/' + 'nested/' * 12 + 'sample.md'])
    def test_source_banner_does_not_change_structural_chapter_count(self, tmp_path, monkeypatch, reported_source):
        source = _make_md_file(tmp_path / 'sample.md', '# The Pragmatic Widget\n\n## Foundations\n\nBody.\n\n## Design Rules\n\nBody.\n\n## Trade-offs\n\nBody.\n\n## Operating Model\n\nBody.\n\n## Closing\n\nBody.\n')
        out_dir = tmp_path / 'output'
        out_text = out_dir / 'full_text.txt'
        out_meta = out_dir / 'metadata.json'
        real_extract = extract_single_file

        def extract_with_reported_source(*args, **kwargs):
            result = real_extract(*args, **kwargs)
            result['source_file'] = reported_source
            return result
        monkeypatch.setattr('sys.argv', ['extract.py', str(source), '--install-missing', 'no'])
        monkeypatch.setattr('book_to_skill.utils.OUTPUT_DIR', out_dir)
        monkeypatch.setattr('book_to_skill.utils.OUTPUT_TEXT', out_text)
        monkeypatch.setattr('book_to_skill.utils.OUTPUT_META', out_meta)
        monkeypatch.setattr('book_to_skill.utils.prepare_dependencies', lambda *a: None)
        monkeypatch.setattr('book_to_skill.utils.extract_single_file', extract_with_reported_source)
        main()
        metadata = json.loads(out_meta.read_text(encoding='utf-8'))
        assert metadata['sources'][0]['chapters_detected'] == 5
        assert metadata['chapters_detected'] == 5
        assert 'SOURCE: sample.md' in out_text.read_text(encoding='utf-8')

    def test_extraction_error_is_not_system_exit(self):
        assert not issubclass(ExtractionError, SystemExit)
        with pytest.raises(ExtractionError):
            raise ExtractionError('test')

class TestInputOrderPreservation:

    def test_explicit_files_preserve_order(self, tmp_path):
        f_c = _make_text_file(tmp_path / 'charlie.txt', 'C')
        f_a = _make_text_file(tmp_path / 'alpha.txt', 'A')
        f_b = _make_text_file(tmp_path / 'bravo.txt', 'B')
        result = resolve_input_files([str(f_c), str(f_a), str(f_b)])
        names = [p.name for p in result]
        assert names == ['charlie.txt', 'alpha.txt', 'bravo.txt'], f'Expected user order, got: {names}'

    def test_explicit_files_reverse_order(self, tmp_path):
        f1 = _make_text_file(tmp_path / 'note2.md', 'two')
        f2 = _make_text_file(tmp_path / 'note1.md', 'one')
        result = resolve_input_files([str(f1), str(f2)])
        names = [p.name for p in result]
        assert names == ['note2.md', 'note1.md'], f'Expected note2 before note1, got: {names}'

    def test_directory_contents_are_sorted(self, tmp_path):
        d = tmp_path / 'books'
        d.mkdir()
        _make_text_file(d / 'zebra.txt', 'Z')
        _make_text_file(d / 'alpha.txt', 'A')
        _make_text_file(d / 'middle.txt', 'M')
        result = resolve_input_files([str(d)])
        names = [p.name for p in result]
        assert names == sorted(names, key=str.lower), f'Directory contents should be sorted, got: {names}'

    def test_mixed_explicit_and_directory(self, tmp_path):
        explicit = _make_text_file(tmp_path / 'explicit_z.txt', 'Z first')
        d = tmp_path / 'folder'
        d.mkdir()
        _make_text_file(d / 'b_in_dir.txt', 'B')
        _make_text_file(d / 'a_in_dir.txt', 'A')
        result = resolve_input_files([str(explicit), str(d)])
        names = [p.name for p in result]
        assert names[0] == 'explicit_z.txt'
        assert names[1:] == ['a_in_dir.txt', 'b_in_dir.txt']

    def test_deduplication_preserves_first_occurrence(self, tmp_path):
        f = _make_text_file(tmp_path / 'dup.txt', 'dup')
        result = resolve_input_files([str(f), str(f)])
        assert len(result) == 1
        assert result[0].name == 'dup.txt'

class TestGlobFiltering:

    def test_glob_filters_unsupported_extensions(self, tmp_path):
        _make_text_file(tmp_path / 'notes.txt', 'good')
        _make_unsupported_file(tmp_path / 'image.png')
        _make_unsupported_file(tmp_path / 'data.csv')
        pattern = str(tmp_path / '*')
        result = resolve_input_files([pattern])
        extensions = {p.suffix.lower() for p in result}
        assert extensions <= SUPPORTED_EXTENSIONS, f'Unsupported extensions found in glob results: {extensions - SUPPORTED_EXTENSIONS}'
        names = [p.name for p in result]
        assert 'notes.txt' in names
        assert 'image.png' not in names
        assert 'data.csv' not in names

    def test_glob_includes_supported_extensions(self, tmp_path):
        _make_text_file(tmp_path / 'readme.md', '# README')
        _make_html_file(tmp_path / 'page.html')
        _make_text_file(tmp_path / 'notes.txt', 'notes')
        pattern = str(tmp_path / '*')
        result = resolve_input_files([pattern])
        names = {p.name for p in result}
        assert 'readme.md' in names
        assert 'page.html' in names
        assert 'notes.txt' in names

    def test_glob_results_are_sorted(self, tmp_path):
        _make_text_file(tmp_path / 'z_file.txt', 'z')
        _make_text_file(tmp_path / 'a_file.txt', 'a')
        _make_text_file(tmp_path / 'm_file.txt', 'm')
        pattern = str(tmp_path / '*.txt')
        result = resolve_input_files([pattern])
        names = [p.name for p in result]
        assert names == sorted(names, key=str.lower)

class TestParseArguments:

    def test_basic_parsing(self):
        paths, mode, _ = parse_arguments(['extract.py', 'book.pdf', '--mode', 'text', '--install-missing', 'no'])
        assert paths == ['book.pdf']
        assert mode == 'text'

    def test_multiple_inputs(self):
        paths, mode, _ = parse_arguments(['extract.py', 'a.pdf', 'b.epub', 'c.txt'])
        assert paths == ['a.pdf', 'b.epub', 'c.txt']
        assert mode == 'text'

    def test_technical_mode(self):
        paths, mode, _ = parse_arguments(['extract.py', 'a.pdf', '--mode', 'technical'])
        assert mode == 'technical'

    def test_invalid_mode_defaults_to_text(self):
        _, mode, _ = parse_arguments(['extract.py', 'a.pdf', '--mode', 'invalid'])
        assert mode == 'text'

class TestEstimateTokens:

    def test_empty_string(self):
        assert estimate_tokens('') == 0

    def test_known_word_count(self):
        text = ' '.join(['word'] * 100)
        tokens = estimate_tokens(text)
        assert tokens == 133

class TestDetectStructure:

    def test_detects_chapters(self):
        text = 'Chapter 1 Introduction\nSome text.\nChapter 2 Details\nMore text.'
        result = detect_structure(text)
        assert result['chapters_detected'] == 2

    def test_detects_chapter_word_with_roman_numeral(self):
        text = '\n'.join(('Chapter %s. Section\nBody text here.' % r for r in ('I', 'II', 'III', 'IV', 'V')))
        assert detect_structure(text)['chapters_detected'] == 5

    def test_detects_thai_chapters(self):
        text = 'บทที่ ๑ ว่าด้วยการวางแผน\nเนื้อหา\nบทที่ ๒ ว่าด้วยการรบ\nเนื้อหา\nบทที่ 3 ว่าด้วยกลยุทธ์\nเนื้อหา'
        assert detect_structure(text)['chapters_detected'] == 3

    def test_thai_episode_headings_and_markdown_prefix(self):
        text = '## ตอนที่ ๘๖ เรื่องหนึ่ง\nเนื้อหา\n## ตอนที่ ๘๗ เรื่องสอง\nเนื้อหา'
        assert detect_structure(text)['chapters_detected'] == 2

    def test_thai_prose_is_not_a_chapter_heading(self):
        from book_to_skill.utils import _chapter_number
        assert _chapter_number('บทความนี้ยาวมากและมีรายละเอียดเยอะ') is None
        assert _chapter_number('ตอนนี้เรามาดูกันว่าเกิดอะไรขึ้น') is None

    def test_korean_je_n_jang(self):
        text = '제1장 총칙\n내용\n제2장 근로시간\n내용\n제3장 휴식\n내용'
        assert detect_structure(text)['chapters_detected'] == 3

    def test_korean_markdown_prefix(self):
        text = '## 제1장 서론\n내용\n## 제2장 본론\n내용'
        assert detect_structure(text)['chapters_detected'] == 2

    def test_korean_inserted_chapter_suffix(self):
        text = '제6장의2 직장 내 괴롭힘의 금지\n내용\n제7장 보칙\n내용'
        assert detect_structure(text)['chapters_detected'] == 2

    def test_korean_article_is_not_chapter(self):
        from book_to_skill.utils import _chapter_number
        assert _chapter_number('제56조 (연장·야간 및 휴일 근로)') is None

    def test_korean_prose_cross_reference_not_chapter(self):
        from book_to_skill.utils import _chapter_number
        assert _chapter_number('이 장과 제5장에서 정한 근로시간…') is None
        assert _chapter_number('제5장에서 정한 근로시간에 관한 규정은…') is None
        assert _chapter_number('제2장의 규정에도 불구하고…') is None

    def test_korean_dedups_toc_and_body(self):
        text = '제1장 총칙\n제2장 근로시간\n## 제1장\n내용\n## 제2장\n내용'
        assert detect_structure(text)['chapters_detected'] == 2

    def test_korean_other_classifiers(self):
        text = '제1편 총칙\n내용\n제2장 정의\n내용\n제3절 통칙\n내용'
        assert detect_structure(text)['chapters_detected'] == 3

    def test_roman_footnote_reference_is_not_a_chapter(self):
        from book_to_skill.utils import _chapter_number
        assert _chapter_number('V. § 19, note.') is None
        assert _chapter_number('VI. § 21:—') is None
        assert _chapter_number('Chapter 6 explores the topic in depth') is None

    def test_detects_toc(self):
        text = 'Table of Contents\n1. Intro\n2. Body'
        result = detect_structure(text)
        assert result['has_toc'] is True

    def test_no_toc(self):
        text = 'Just some regular text without any structure.'
        result = detect_structure(text)
        assert result['has_toc'] is False

    def test_toc_chinese(self):
        assert detect_structure('目录\n第一章 开始\n第二章 进阶\n')['has_toc'] is True

    def test_toc_japanese(self):
        assert detect_structure('目次\n本文')['has_toc'] is True

    def test_toc_french(self):
        assert detect_structure('Table des matières\n1 Intro')['has_toc'] is True

    def test_toc_german(self):
        assert detect_structure('Inhaltsverzeichnis\n1 Einleitung')['has_toc'] is True

    def test_toc_italian(self):
        assert detect_structure('Indice\n1 Introduzione')['has_toc'] is True

    def test_toc_dutch(self):
        assert detect_structure('Inhoudsopgave\n1 Inleiding')['has_toc'] is True

    def test_toc_spanish_accented(self):
        assert detect_structure('Índice\n1 Introducción')['has_toc'] is True

    def test_toc_portuguese_unaccented(self):
        assert detect_structure('Sumario\n1 Introdução')['has_toc'] is True

    def test_toc_traditional_chinese(self):
        assert detect_structure('目錄\n第一章')['has_toc'] is True

    @pytest.mark.parametrize('header', ['目 录', '目\u3000录', '目 次', '目\u3000次'])
    def test_toc_cjk_headers_allow_extracted_whitespace(self, header):
        assert detect_structure(f'{header}\n第一章 开始\n第二章 进阶')['has_toc'] is True

    def test_toc_italian_sommario(self):
        assert detect_structure('Sommario\n1 Introduzione')['has_toc'] is True

    def test_toc_inline_word_is_not_toc(self):
        text = 'The contents of this chapter are varied and the index is long.\n'
        assert detect_structure(text)['has_toc'] is False

    def test_numbered_list_items_are_not_chapters(self):
        text = '1. Compared to characters, tokens allow the model to break words into\n2. Because there are fewer unique tokens than unique words, this reduces\n3. Tokens also help the model process unknown words, for instance a word\n'
        assert detect_structure(text)['chapters_detected'] == 0

    def test_inline_cross_references_are_not_chapters(self):
        text = 'Chapter 6 explores why context is important for a model to perform.\nAs discussed, Chapter 8 are relevant beyond finetuning in this case.\n'
        assert detect_structure(text)['chapters_detected'] == 0

    def test_years_are_not_chapters(self):
        text = '2025. AI is often mentioned as a competitive advantage these days.\n'
        assert detect_structure(text)['chapters_detected'] == 0

    def test_real_headings_with_titles_count(self):
        text = 'Chapter 1. Introduction to Building AI\nbody\nChapter 2. Understanding Models\nbody\n'
        assert detect_structure(text)['chapters_detected'] == 2

    def test_portuguese_capitulo(self):
        text = 'Capítulo 1\nalgum texto\nCapítulo 2\nmais texto\n'
        assert detect_structure(text)['chapters_detected'] == 2

    def test_distinct_numbering_dedups_toc_and_body(self):
        text = 'Capítulo 1: Alicerces\n...\nCapítulo 1\nbody of chapter one\n'
        assert detect_structure(text)['chapters_detected'] == 1

    def test_roman_numeral_chapters(self):
        text = 'I: Loomings\nbody\nII: The Carpet-Bag\nbody\nIII: The Spouter-Inn\nbody\n'
        assert detect_structure(text)['chapters_detected'] == 3

    def test_roman_requires_title_after_separator(self):
        assert detect_structure('V.\nI\nII\n')['chapters_detected'] == 0

    def test_roman_rejects_non_canonical(self):
        assert detect_structure('IIII: Bad\nVV: Also bad\n')['chapters_detected'] == 0

    def test_scans_full_text_not_just_head(self):
        text = 'Capítulo 1\n' + 'filler word ' * 6000 + '\nCapítulo 2\n'
        assert detect_structure(text)['chapters_detected'] == 2

    def test_chinese_di_n_zhang(self):
        text = '第一章 绪论\n正文。\n第二章 方法\n更多正文。\n'
        assert detect_structure(text)['chapters_detected'] == 2

    def test_japanese_fullwidth_digit_chapters(self):
        text = '第１章 はじめに\n本文。\n第２章 つぎ\n本文。\n'
        assert detect_structure(text)['chapters_detected'] == 2

    def test_fullwidth_multi_digit_chapter(self):
        text = '第１章 序\n第１０章 終\n'
        assert detect_structure(text)['chapters_detected'] == 2

    def test_chinese_di_n_jiang_lecture(self):
        text = '第一讲\n正文\n第二讲\n正文\n第三讲\n正文\n'
        assert detect_structure(text)['chapters_detected'] == 3

    def test_markdown_cjk_ordinal_heading(self):
        text = '## 一 · 缘起\n正文\n## 二 · 主体\n正文\n## 三 · 结语\n正文\n'
        assert detect_structure(text)['chapters_detected'] == 3

    def test_markdown_di_n_jiang_heading(self):
        text = '## 第一讲\n正文\n## 第二讲\n正文\n'
        assert detect_structure(text)['chapters_detected'] == 2

    def test_chinese_dedups_toc_and_body(self):
        text = '第一讲..... 2\n第二讲..... 12\n## 第一讲\n正文\n## 第二讲\n正文\n'
        assert detect_structure(text)['chapters_detected'] == 2

    def test_cjk_detection_does_not_affect_latin(self):
        assert detect_structure('## 5 Setup\n## 6 Teardown\n')['chapters_detected'] == 0

    def test_markdown_atx_chapters(self):
        text = '# Book Title\n\n## Introduction\nbody\n\n## Getting Started\nbody\n\n## Advanced\nbody\n'
        assert detect_structure(text)['chapters_detected'] == 3

    def test_markdown_all_h1_chapters(self):
        text = '# Chapter One\ntext\n# Chapter Two\ntext\n# Chapter Three\ntext\n'
        assert detect_structure(text)['chapters_detected'] == 3

    def test_asciidoc_section_headings(self):
        text = '= Doc Title\n\n== First Section\nbody\n\n== Second Section\nbody\n'
        assert detect_structure(text)['chapters_detected'] == 2

    def test_asciidoc_deeper_levels(self):
        text = '=== Alpha\nbody\n=== Beta\nbody\n=== Gamma\nbody\n'
        assert detect_structure(text)['chapters_detected'] == 3

    def test_markdown_prefixed_chapter_word(self):
        text = '## Chapter 1: Intro\nbody\n## Chapter 2: Models\nbody\n'
        assert detect_structure(text)['chapters_detected'] == 2

    def test_headings_inside_code_fence_are_ignored(self):
        text = '# Real A\n\n```python\n# a comment\n# another comment\n```\n\n# Real B\n'
        assert detect_structure(text)['chapters_detected'] == 2

    def test_plain_prose_has_no_structural_chapters(self):
        text = 'Just paragraphs of prose.\nMore prose here.\n'
        assert detect_structure(text)['chapters_detected'] == 0

    def test_numeric_chapters_win_over_markdown_subsections(self):
        text = 'Chapter 1: Intro\n## sub a\n## sub b\n## sub c\nChapter 2: Next\n'
        assert detect_structure(text)['chapters_detected'] == 2

    def test_chinese_numeral_parsing(self):
        assert _cn_numeral_to_int('一') == 1
        assert _cn_numeral_to_int('十') == 10
        assert _cn_numeral_to_int('十一') == 11
        assert _cn_numeral_to_int('二十') == 20
        assert _cn_numeral_to_int('二十一') == 21
        assert _cn_numeral_to_int('一百零八') == 108
        assert _cn_numeral_to_int('15') == 15
        assert _cn_numeral_to_int('１２') == 12
        assert _cn_numeral_to_int('不是数字') is None
        assert _cn_numeral_to_int('9999') is None

    def test_french_chapitre(self):
        assert detect_structure('Chapitre 1\nx\nChapitre 2\nx')['chapters_detected'] == 2

    def test_german_kapitel(self):
        assert detect_structure('Kapitel 1\nx\nKapitel 2\nx')['chapters_detected'] == 2

    def test_italian_capitolo(self):
        assert detect_structure('Capitolo 1\nx\nCapitolo 2\nx')['chapters_detected'] == 2

    def test_dutch_hoofdstuk(self):
        assert detect_structure('Hoofdstuk 1\nx\nHoofdstuk 2\nx')['chapters_detected'] == 2

    def test_german_kapitel_with_title(self):
        text = 'Kapitel 1: Einführung\nx\nKapitel 2: Methoden\nx'
        assert detect_structure(text)['chapters_detected'] == 2

    def test_european_lowercase_cross_reference_not_chapter(self):
        text = 'Kapitel 3 behandelt das Thema ausführlich.\nChapitre 6 explique le contexte ici.\n'
        assert detect_structure(text)['chapters_detected'] == 0

    def test_german_kapitel_umlaut_title(self):
        text = 'Kapitel 1 Anfang\nx\nKapitel 2 Überblick\nx'
        assert detect_structure(text)['chapters_detected'] == 2

    def test_roman_heading_umlaut_title(self):
        text = 'I: Überblick\nbody\nII: Anfang\nbody\n'
        assert detect_structure(text)['chapters_detected'] == 2

    def test_setext_rst_equals_three_sections(self):
        text = 'Introduction\n============\nbody\n\nGetting Started\n===============\nbody\n\nAdvanced\n========\nbody\n'
        assert detect_structure(text)['chapters_detected'] == 3

    def test_setext_rst_dash_two_sections(self):
        text = 'Methods\n-------\nbody\n\nResults\n-------\nbody\n'
        assert detect_structure(text)['chapters_detected'] == 2

    def test_setext_markdown_h1(self):
        text = 'First\n=====\ntext\n\nSecond\n======\ntext\n'
        assert detect_structure(text)['chapters_detected'] == 2

    def test_setext_equals_top_level_wins_over_dash(self):
        text = 'Chap One\n========\nSec a\n-----\nSec b\n-----\nChap Two\n========\n'
        assert detect_structure(text)['chapters_detected'] == 2

    def test_setext_thematic_break_under_paragraph_not_heading(self):
        text = 'This is a normal paragraph of body text.\n---\nmore text follows here too.\n'
        assert detect_structure(text)['chapters_detected'] == 0

    def test_setext_horizontal_rule_with_blank_above_not_heading(self):
        text = 'text here\n\n---\n\nmore\n\n***\n'
        assert detect_structure(text)['chapters_detected'] == 0

    def test_setext_simple_table_border_not_heading(self):
        text = 'Name    Value\n=====   =====\nfoo     1\nbar     2\n'
        assert detect_structure(text)['chapters_detected'] == 0

    def test_setext_yaml_front_matter_not_heading(self):
        text = '---\ntitle: foo\nauthor: bar\n---\nbody text here\n'
        assert detect_structure(text)['chapters_detected'] == 0

    def test_setext_inside_code_fence_ignored(self):
        text = '```\nTitle\n=====\nAnother\n=======\n```\n'
        assert detect_structure(text)['chapters_detected'] == 0

    def test_atx_all_punctuation_title_not_heading(self):
        text = 'intro line\n=====   =====\nbody\n'
        assert detect_structure(text)['chapters_detected'] == 0

    def test_atx_heading_followed_by_underline_not_double_counted(self):
        text = '# Hi\n====\n# Bye\n=====\n'
        assert detect_structure(text)['chapters_detected'] == 2

class TestMarkdownPrefixedLatinChapters:

    def test_md_prefixed_latin_chapter_word(self):
        from book_to_skill.utils import _chapter_number
        assert _chapter_number('## Chapter 1') == 1
        assert _chapter_number('## CHAPTER 5') == 5
        assert _chapter_number('## Chapter 1 Interaction Design') == 1
        assert _chapter_number('## Capítulo 5') == 5
        assert _chapter_number('## Chapitre 2') == 2
        assert _chapter_number('## Kapitel 3') == 3

    def test_asciidoc_prefixed_chapter_word(self):
        from book_to_skill.utils import _chapter_number
        assert _chapter_number('== Chapter 1') == 1
        assert _chapter_number('=== Chapter 2') == 2

    def test_md_prefixed_roman_numeral(self):
        from book_to_skill.utils import _chapter_number
        assert _chapter_number('## I. Loomings') == 1
        assert _chapter_number('## III: The Spouter-Inn') == 3

    def test_issue91_repro_matches_plain_text_count(self):
        md = '\n'.join((f'## Chapter {i}\n## Some Section\nbody\n' for i in range(1, 36)))
        plain = '\n'.join((f'Chapter {i}\nbody\n' for i in range(1, 36)))
        assert detect_structure(md)['chapters_detected'] == 35
        assert detect_structure(plain)['chapters_detected'] == 35
        sample = detect_structure(md)['chapter_headings_sample']
        assert sample and sample[0] == '## Chapter 1'

    def test_md_prefixed_lowercase_roman_still_works(self):
        text = '## i. introduction\nbody\n## ii. methods\nbody\n## iii. results\nbody\n'
        assert detect_structure(text)['chapters_detected'] == 3

    def test_md_prefixed_non_chapter_headings_still_rejected(self):
        from book_to_skill.utils import _chapter_number
        assert _chapter_number('## Some Section') is None
        assert _chapter_number('## 5 Setup') is None
        assert _chapter_number('## Acknowledgment') is None
        assert _chapter_number('## 2025 Goals') is None

    def test_md_prefixed_cjk_unchanged(self):
        assert detect_structure('## 第一讲\n正文\n## 第二讲\n正文\n')['chapters_detected'] == 2
        assert detect_structure('## 一 · 缘起\n正文\n## 二 · 主体\n正文\n')['chapters_detected'] == 2

class TestTextExtraction:

    def test_extract_txt_file(self, tmp_path):
        txt = _make_text_file(tmp_path / 'simple.txt', 'Simple text content for testing.')
        with mock.patch('book_to_skill.utils.prepare_dependencies'):
            result = extract_single_file(txt, 'text', 'no')
        assert result['format'] == 'txt'
        assert result['extraction_method'] == 'plain-text'
        assert 'Simple text content' in result['text']

    def test_extract_md_file(self, tmp_path):
        md = _make_md_file(tmp_path / 'notes.md', '# My Notes\n\nSome notes here.')
        with mock.patch('book_to_skill.utils.prepare_dependencies'):
            result = extract_single_file(md, 'text', 'no')
        assert result['format'] == 'md'
        assert 'My Notes' in result['text']

class TestHtmlExtraction:

    def test_extract_html_file(self, tmp_path):
        html_file = _make_html_file(tmp_path / 'page.html')
        with mock.patch('book_to_skill.utils.prepare_dependencies'):
            result = extract_single_file(html_file, 'text', 'no')
        assert result['format'] == 'html'
        assert result['extraction_method'] == 'html-parser'
        assert 'Test paragraph' in result['text']

class TestDocxExtraction:

    def test_extract_docx_zipfile_fallback(self, tmp_path):
        docx = _make_minimal_docx(tmp_path / 'test.docx')
        with mock.patch('book_to_skill.utils.prepare_dependencies'):
            result = extract_single_file(docx, 'text', 'no')
        assert result['format'] == 'docx'
        assert 'DOCX test paragraph' in result['text']

    def test_extract_docx_zipfile_xxe_rejection_direct_call(self, tmp_path):
        ns = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
        xml = textwrap.dedent(f'            <?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n            <!DOCTYPE w:document [\n              <!ENTITY xxe SYSTEM "file:///etc/passwd">\n            ]>\n            <w:document xmlns:w="{ns}">\n              <w:body>\n                <w:p><w:r><w:t>&xxe;</w:t></w:r></w:p>\n              </w:body>\n            </w:document>\n        ')
        bad_docx = tmp_path / 'malicious.docx'
        with zipfile.ZipFile(bad_docx, 'w') as zf:
            zf.writestr('word/document.xml', xml)
            zf.writestr('[Content_Types].xml', '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        with pytest.raises(ExtractionError, match='Security validation failed'):
            extract_docx_with_zipfile(str(bad_docx))

    def test_extract_docx_python_docx_xxe_rejection_direct_call(self, tmp_path):
        from book_to_skill.parsers.docx import extract_docx_with_python_docx
        ns = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
        xml = textwrap.dedent(f'            <?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n            <!DOCTYPE w:document [\n              <!ENTITY xxe SYSTEM "file:///etc/passwd">\n            ]>\n            <w:document xmlns:w="{ns}">\n              <w:body>\n                <w:p><w:r><w:t>&xxe;</w:t></w:r></w:p>\n              </w:body>\n            </w:document>\n        ')
        bad_docx = tmp_path / 'malicious.docx'
        with zipfile.ZipFile(bad_docx, 'w') as zf:
            zf.writestr('word/document.xml', xml)
            zf.writestr('[Content_Types].xml', '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        with mock.patch.dict(sys.modules, {'docx': mock.MagicMock()}):
            with pytest.raises(ExtractionError, match='Security validation failed'):
                extract_docx_with_python_docx(str(bad_docx))

    def test_extract_docx_python_docx_absent_skips_validation_without_raising(self, tmp_path):
        from book_to_skill.parsers.docx import extract_docx_with_python_docx
        real_import = __import__

        def fake_import(name, *args, **kwargs):
            if name == 'docx':
                raise ImportError('simulated: python-docx not installed')
            return real_import(name, *args, **kwargs)
        docx_path = tmp_path / 'whatever.docx'
        docx_path.write_bytes(b'not even a real docx')
        with mock.patch('builtins.__import__', side_effect=fake_import):
            result = extract_docx_with_python_docx(str(docx_path))
        assert result is None

    def test_extract_docx_xxe_rejection(self, tmp_path):
        from book_to_skill.parsers.docx import extract_docx
        ns = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
        xml = textwrap.dedent(f'            <?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n            <!DOCTYPE w:document [\n              <!ENTITY xxe SYSTEM "file:///etc/passwd">\n            ]>\n            <w:document xmlns:w="{ns}">\n              <w:body>\n                <w:p><w:r><w:t>&xxe;</w:t></w:r></w:p>\n              </w:body>\n            </w:document>\n        ')
        bad_docx = tmp_path / 'malicious.docx'
        with zipfile.ZipFile(bad_docx, 'w') as zf:
            zf.writestr('word/document.xml', xml)
            zf.writestr('[Content_Types].xml', '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        with pytest.raises(ExtractionError, match='Security validation failed'):
            extract_docx(str(bad_docx))

    def test_extract_docx_validates_once_when_python_docx_unavailable(self, tmp_path):
        from book_to_skill.parsers import docx as docx_module
        docx_path = _make_minimal_docx(tmp_path / 'test.docx')
        real_import = __import__

        def fake_import(name, *args, **kwargs):
            if name == 'docx':
                raise ImportError('simulated: python-docx not installed')
            return real_import(name, *args, **kwargs)
        with mock.patch.object(docx_module, 'validate_docx_xml_safety', wraps=docx_module.validate_docx_xml_safety) as spy:
            with mock.patch('builtins.__import__', side_effect=fake_import):
                text, method = docx_module.extract_docx(str(docx_path))
        assert method == 'zipfile-docx'
        assert 'DOCX test paragraph' in text
        assert spy.call_count == 1

class TestResolveInputFiles:

    def test_nonexistent_file_kept_for_error_reporting(self, tmp_path):
        fake = tmp_path / 'nonexistent.pdf'
        result = resolve_input_files([str(fake)])
        assert len(result) == 1
        assert result[0].name == 'nonexistent.pdf'

    def test_empty_directory_returns_empty(self, tmp_path):
        d = tmp_path / 'empty'
        d.mkdir()
        result = resolve_input_files([str(d)])
        assert result == []

    def test_directory_only_picks_supported(self, tmp_path):
        d = tmp_path / 'mixed'
        d.mkdir()
        _make_text_file(d / 'readme.txt', 'hi')
        _make_unsupported_file(d / 'photo.jpg')
        result = resolve_input_files([str(d)])
        names = [p.name for p in result]
        assert 'readme.txt' in names
        assert 'photo.jpg' not in names

class TestDependencyCheck:

    def test_all_present_reports_ready(self, capsys):
        from book_to_skill.dependencies import run_dependency_check
        with mock.patch('book_to_skill.dependencies.python_module_available', return_value=True), mock.patch('book_to_skill.dependencies.shutil.which', return_value='/usr/bin/tool'):
            code = run_dependency_check()
        out = capsys.readouterr().out
        assert code == 0
        assert 'All optional dependencies are installed' in out
        assert '✗' not in out

    def test_all_missing_lists_install_commands(self, capsys):
        from book_to_skill.dependencies import run_dependency_check
        with mock.patch('book_to_skill.dependencies.python_module_available', return_value=False), mock.patch('book_to_skill.dependencies.shutil.which', return_value=None):
            code = run_dependency_check()
        out = capsys.readouterr().out
        assert code == 0
        assert 'pip install' in out
        assert 'docling' in out and 'striprtf' in out
        assert 'MISSING — required, no fallback' in out
        assert 'calibre-ebook.com' in out

    def test_pdftotext_alone_satisfies_pdf_text(self, capsys):
        from book_to_skill.dependencies import run_dependency_check

        def which(cmd):
            return '/usr/bin/pdftotext' if cmd == 'pdftotext' else None
        with mock.patch('book_to_skill.dependencies.python_module_available', return_value=False), mock.patch('book_to_skill.dependencies.shutil.which', side_effect=which):
            run_dependency_check()
        out = capsys.readouterr().out
        pdf_block = out.split('PDF (text-heavy)', 1)[1].split('PDF (technical', 1)[0]
        assert 'ready' in pdf_block

class TestParserExceptionLogging:

    def test_pypdf_warns_on_unexpected_error_and_returns_none(self, tmp_path, capsys):
        from book_to_skill.parsers.pdf import extract_with_pypdf
        broken = tmp_path / 'broken.pdf'
        broken.write_bytes(b'%PDF-1.4 fake')
        real_import = __import__

        def fake_import(name, *args, **kwargs):
            if name == 'pypdf':
                raise RuntimeError('simulated failure')
            return real_import(name, *args, **kwargs)
        with mock.patch('builtins.__import__', side_effect=fake_import):
            result = extract_with_pypdf(str(broken))
        assert result is None
        captured = capsys.readouterr()
        assert '[warn]' in captured.err
        assert 'failed:' in captured.err

class TestRtfUnicodeFallback:
    _BS = chr(92)

    def _esc(self, codepoint, fallback='?'):
        return self._BS + 'u' + str(codepoint) + fallback

    def test_rtf_unicode_right_single_quote(self):
        assert strip_rtf_fallback('It' + self._esc(8217) + 's') == 'It’s'

    def test_rtf_unicode_em_dash(self):
        assert strip_rtf_fallback('a ' + self._esc(8212) + ' b') == 'a — b'

    def test_rtf_unicode_accented_letter(self):
        assert strip_rtf_fallback('caf' + self._esc(233)) == 'café'

    def test_rtf_unicode_hex_fallback_consumed(self):
        text = 'x' + self._BS + 'u8217' + self._BS + "'92y"
        assert strip_rtf_fallback(text) == 'x’y'

    def test_rtf_unicode_space_delimited_fallback(self):
        text = 'x' + self._BS + 'u8217 ?y'
        assert strip_rtf_fallback(text) == 'x’y'

    def test_rtf_unicode_negative_codepoint(self):
        assert strip_rtf_fallback(self._esc(-3)) == '�'

    def test_rtf_fallback_without_unicode_unchanged(self):
        assert strip_rtf_fallback(self._BS + 'b0 Bold' + self._BS + 'b0 off') == 'Boldoff'
        assert strip_rtf_fallback('{' + self._BS + 'rtf1 hi}') == 'hi'

    def test_rtf_unicode_consecutive_escapes_with_hex_fallback(self):
        text = self._BS + 'u8220' + self._BS + "'93Hi" + self._BS + 'u8221' + self._BS + "'94"
        assert strip_rtf_fallback(text) == '“Hi”'

class TestHtmlEntityDecoding:

    def _text(self, fragment):
        from book_to_skill.parsers.html import _HTMLTextExtractor
        p = _HTMLTextExtractor()
        p.feed(fragment)
        return p.get_text()

    def test_double_encoded_ampersand(self):
        assert self._text('&amp;amp;') == '&amp;'

    def test_double_encoded_tag(self):
        assert self._text('&amp;lt;tag&amp;gt;') == '&lt;tag&gt;'

    def test_single_entities_still_decode(self):
        assert self._text('&lt;b&gt;') == '<b>'
        assert self._text('&amp;') == '&'

    def test_numeric_and_named_entities(self):
        assert self._text('&#233;') == 'é'
        assert self._text('&#xE9;') == 'é'
        assert self._text('&copy;') == '©'
        assert self._text('hello') == 'hello'

    def test_skip_tag_content_excluded(self):
        assert self._text('<style>x{}</style>keep') == 'keep'

class TestDocxTableReconstruction:
    _NS = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'

    def _make_docx(self, tmp_path, body_xml):
        import zipfile
        p = tmp_path / 't.docx'
        doc = f'<?xml version="1.0"?><w:document xmlns:w="{self._NS}"><w:body>{body_xml}</w:body></w:document>'
        with zipfile.ZipFile(p, 'w') as zf:
            zf.writestr('word/document.xml', doc)
        return str(p)

    def _para(self, text):
        return f'<w:p><w:r><w:t>{text}</w:t></w:r></w:p>'

    def _cell(self, text):
        return f'<w:tc><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:tc>'

    def test_table_rows_are_tab_joined(self, tmp_path):
        body = self._para('Intro') + '<w:tbl><w:tr>' + self._cell('Name') + self._cell('Value') + '</w:tr>' + '<w:tr>' + self._cell('foo') + self._cell('1') + '</w:tr></w:tbl>'
        out = extract_docx_with_zipfile(self._make_docx(tmp_path, body))
        assert 'Name\tValue' in out
        assert 'foo\t1' in out

    def test_document_order_preserved(self, tmp_path):
        body = self._para('Before') + '<w:tbl><w:tr>' + self._cell('R1C1') + self._cell('R1C2') + '</w:tr></w:tbl>' + self._para('After')
        out = extract_docx_with_zipfile(self._make_docx(tmp_path, body))
        assert out.index('Before') < out.index('R1C1') < out.index('After')

    def test_paragraph_only_document_unchanged(self, tmp_path):
        body = self._para('Just a paragraph') + self._para('And another')
        out = extract_docx_with_zipfile(self._make_docx(tmp_path, body))
        assert out == 'Just a paragraph\nAnd another'

    def test_empty_cell_still_tab_joined(self, tmp_path):
        body = '<w:tbl><w:tr>' + self._cell('A') + '<w:tc><w:p></w:p></w:tc></w:tr></w:tbl>'
        out = extract_docx_with_zipfile(self._make_docx(tmp_path, body))
        assert out == 'A\t'

    def test_sdt_wrapped_content_is_preserved(self, tmp_path):
        body = self._para('Before') + '<w:sdt><w:sdtContent>' + self._para('Inside SDT') + '</w:sdtContent></w:sdt>' + self._para('After')
        out = extract_docx_with_zipfile(self._make_docx(tmp_path, body))
        assert out == 'Before\nInside SDT\nAfter'

class TestEpubSpineOrder:

    def _make_epub(self, tmp_path, opf_xml, files, opf_name='content.opf'):
        p = tmp_path / 'book.epub'
        with zipfile.ZipFile(p, 'w') as zf:
            zf.writestr('mimetype', 'application/epub+zip')
            zf.writestr('META-INF/container.xml', f'<?xml version="1.0"?><container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0"><rootfiles><rootfile full-path="{opf_name}" media-type="application/oebps-package+xml"/></rootfiles></container>')
            zf.writestr(opf_name, opf_xml)
            for name, html in files.items():
                zf.writestr(name, html)
        return str(p)

    def _doc(self, text):
        return f'<html><body><p>{text}</p></body></html>'

    def test_spine_order_overrides_manifest_order(self, tmp_path):
        opf = '<package xmlns="http://www.idpf.org/2007/opf" version="3.0"><manifest><item id="c2" href="ch2.xhtml" media-type="application/xhtml+xml"/><item id="c1" href="ch1.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="c1"/><itemref idref="c2"/></spine></package>'
        files = {'ch1.xhtml': self._doc('FIRST'), 'ch2.xhtml': self._doc('SECOND')}
        out = extract_with_zipfile(self._make_epub(tmp_path, opf, files))
        assert out.index('FIRST') < out.index('SECOND')

    def test_non_spine_doc_kept_as_safety_net_after_spine(self, tmp_path):
        opf = '<package xmlns="http://www.idpf.org/2007/opf" version="3.0"><manifest><item id="c1" href="ch1.xhtml" media-type="application/xhtml+xml"/><item id="nav" href="nav.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="c1"/></spine></package>'
        files = {'ch1.xhtml': self._doc('CONTENT'), 'nav.xhtml': self._doc('NAVTOC')}
        out = extract_with_zipfile(self._make_epub(tmp_path, opf, files))
        assert 'NAVTOC' in out
        assert out.index('CONTENT') < out.index('NAVTOC')

    def test_item_attribute_order_robust(self, tmp_path):
        opf = '<package xmlns="http://www.idpf.org/2007/opf" version="3.0"><manifest><item href="only.xhtml" id="c1" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="c1"/></spine></package>'
        files = {'only.xhtml': self._doc('ONLY')}
        out = extract_with_zipfile(self._make_epub(tmp_path, opf, files))
        assert 'ONLY' in out

    def test_spine_absent_uses_safety_net(self, tmp_path):
        opf = '<package xmlns="http://www.idpf.org/2007/opf" version="3.0"><manifest><item id="a" href="a.xhtml" media-type="application/xhtml+xml"/></manifest></package>'
        files = {'a.xhtml': self._doc('ALPHA')}
        out = extract_with_zipfile(self._make_epub(tmp_path, opf, files))
        assert 'ALPHA' in out

    def test_opf_in_subdir_resolves_hrefs(self, tmp_path):
        opf = '<package xmlns="http://www.idpf.org/2007/opf" version="3.0"><manifest><item id="c1" href="ch1.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="c1"/></spine></package>'
        files = {'OEBPS/ch1.xhtml': self._doc('SUBDIR')}
        out = extract_with_zipfile(self._make_epub(tmp_path, opf, files, opf_name='OEBPS/content.opf'))
        assert 'SUBDIR' in out

    def test_non_self_closing_item_tag(self, tmp_path):
        opf = '<package xmlns="http://www.idpf.org/2007/opf" version="3.0"><manifest><item id="c1" href="ch1.xhtml" media-type="application/xhtml+xml"></item></manifest><spine><itemref idref="c1"></itemref></spine></package>'
        files = {'ch1.xhtml': self._doc('NONSELFCLOSE')}
        out = extract_with_zipfile(self._make_epub(tmp_path, opf, files))
        assert 'NONSELFCLOSE' in out

    def test_no_opf_falls_back_to_sorted_files(self, tmp_path):
        p = tmp_path / 'noopf.epub'
        with zipfile.ZipFile(p, 'w') as zf:
            zf.writestr('mimetype', 'application/epub+zip')
            zf.writestr('a.xhtml', self._doc('AAA'))
            zf.writestr('b.xhtml', self._doc('BBB'))
        out = extract_with_zipfile(str(p))
        assert 'AAA' in out and 'BBB' in out

class TestTextEncodingDetection:
    SAMPLE = 'Café — naïve résumé\nSecond line'

    def _write(self, tmp_path, raw_bytes):
        p = tmp_path / 'sample.txt'
        p.write_bytes(raw_bytes)
        return str(p)

    def test_utf16_le_bom(self, tmp_path):
        raw = b'\xff\xfe' + self.SAMPLE.encode('utf-16-le')
        assert read_text_file(self._write(tmp_path, raw)) == self.SAMPLE

    def test_utf16_be_bom(self, tmp_path):
        raw = b'\xfe\xff' + self.SAMPLE.encode('utf-16-be')
        assert read_text_file(self._write(tmp_path, raw)) == self.SAMPLE

    def test_utf32_le_bom(self, tmp_path):
        raw = b'\xff\xfe\x00\x00' + self.SAMPLE.encode('utf-32-le')
        assert read_text_file(self._write(tmp_path, raw)) == self.SAMPLE

    def test_utf8_bom(self, tmp_path):
        raw = b'\xef\xbb\xbf' + self.SAMPLE.encode('utf-8')
        assert read_text_file(self._write(tmp_path, raw)) == self.SAMPLE

    def test_utf8_no_bom(self, tmp_path):
        raw = self.SAMPLE.encode('utf-8')
        assert read_text_file(self._write(tmp_path, raw)) == self.SAMPLE

    def test_cp1252_no_bom(self, tmp_path):
        raw = 'café'.encode('cp1252')
        assert read_text_file(self._write(tmp_path, raw)) == 'café'

    def test_ascii_no_bom(self, tmp_path):
        assert read_text_file(self._write(tmp_path, b'hello world')) == 'hello world'

    def test_utf32_be_bom(self, tmp_path):
        raw = b'\x00\x00\xfe\xff' + self.SAMPLE.encode('utf-32-be')
        assert read_text_file(self._write(tmp_path, raw)) == self.SAMPLE

    def test_empty_file_returns_empty_string(self, tmp_path):
        assert read_text_file(self._write(tmp_path, b'')) == ''

class TestPdftotextEncoding:

    def test_pdftotext_decodes_as_utf8(self, monkeypatch):
        captured = {}

        class _Result:
            returncode = 0
            stdout = 'Café — naïve'
        monkeypatch.setattr(pdf_parser.shutil, 'which', lambda name: '/usr/bin/pdftotext')

        def fake_run(cmd, **kwargs):
            captured.update(kwargs)
            return _Result()
        monkeypatch.setattr(pdf_parser.subprocess, 'run', fake_run)
        assert pdf_parser.extract_with_pdftotext('x.pdf') == 'Café — naïve'
        assert captured.get('encoding') == 'utf-8'
        assert captured.get('errors') == 'replace'

class TestLooksImageOnly:

    def _probe(self, monkeypatch, stdout, *, has_pdftotext=True):
        captured = {}

        class _Result:
            returncode = 0
        _Result.stdout = stdout
        monkeypatch.setattr(pdf_parser.shutil, 'which', lambda name: '/usr/bin/pdftotext' if has_pdftotext else None)

        def fake_run(cmd, **kwargs):
            captured['cmd'] = cmd
            return _Result()
        monkeypatch.setattr(pdf_parser.subprocess, 'run', fake_run)
        return captured

    def test_no_text_in_first_pages_is_image_only(self, monkeypatch):
        captured = self._probe(monkeypatch, '\n\x0c\n  \x0c')
        assert pdf_parser.looks_image_only('scan.pdf') is True
        assert '-l' in captured['cmd'] and captured['cmd'][captured['cmd'].index('-l') + 1] == '5'

    def test_text_in_first_pages_is_not_image_only(self, monkeypatch):
        self._probe(monkeypatch, 'Chapter 1\nOnce upon a time')
        assert pdf_parser.looks_image_only('book.pdf') is False

    def test_without_pdftotext_probe_is_skipped(self, monkeypatch):
        self._probe(monkeypatch, '', has_pdftotext=False)
        assert pdf_parser.looks_image_only('scan.pdf') is False

    def test_extraction_fails_early_with_ocr_hint(self, monkeypatch, tmp_path):
        from book_to_skill import utils
        pdf = tmp_path / 'scan.pdf'
        pdf.write_bytes(b'%PDF-1.4\n')
        monkeypatch.setattr(utils, 'looks_image_only', lambda path: True)
        with pytest.raises(ExtractionError) as exc:
            utils.extract_single_file(pdf, 'text', 'no')
        assert 'scanned' in str(exc.value)
        assert 'ocrmypdf' in str(exc.value)

class TestPdftotextCleanup:

    def _pages(self, *pages):
        return '\x0c'.join(pages)

    def test_repeated_header_and_edge_page_numbers_removed(self):
        raw = self._pages(*(f'BOOK TITLE\nReal content on page {n}.\n{n}' for n in (1, 2, 3)))
        out = pdf_parser.clean_pdftotext(raw)
        assert 'BOOK TITLE' not in out
        assert not any((ln.strip() in {'1', '2', '3'} for ln in out.splitlines()))
        assert 'Real content on page 1.' in out

    def test_hyphenated_wrap_is_rejoined(self):
        raw = self._pages(*(f'H\nabout informa-\ntion here\n{n}' for n in (1, 2, 3)))
        out = pdf_parser.clean_pdftotext(raw)
        assert 'information' in out
        assert 'informa-' not in out

    def test_token_count_drops(self):
        raw = self._pages(*(f'RUNNING HEAD\nbody text page {n}\n{n}' for n in (1, 2, 3)))
        out = pdf_parser.clean_pdftotext(raw)
        assert len(out.split()) < len(raw.split())

    def test_mid_page_bare_number_is_kept(self):
        raw = self._pages(*(f'HDR\nthe answer is 42\ntrailing\n{n}' for n in (1, 2, 3)))
        out = pdf_parser.clean_pdftotext(raw)
        assert '42' in out
        assert 'HDR' not in out

    def test_single_page_keeps_content(self):
        out = pdf_parser.clean_pdftotext('Title\nword-\nwrap\n1')
        assert 'wordwrap' in out
        assert 'Title' in out
        assert '1' in out

class TestLowercaseRomanNumerals:

    def test_lowercase_roman_requires_heading_context(self):
        assert detect_structure('i: Loomings\nbody\nii: The Carpet-Bag\nbody\n')['chapters_detected'] == 0

    def test_lowercase_roman_with_markdown_heading(self):
        text = '## i. introduction\nbody\n## ii. methods\nbody\n## iii. results\nbody\n'
        assert detect_structure(text)['chapters_detected'] == 3

    def test_bare_lowercase_not_confused_with_prose(self):
        from book_to_skill.utils import _chapter_number
        assert _chapter_number('i') is None
        assert _chapter_number('v.') is None
        assert _chapter_number('i.') is None
        assert _chapter_number('vi: the vim editor') is None
        assert _chapter_number('cli: a reference') is None
        assert _chapter_number('civ: a history') is None

    def test_uppercase_roman_still_works(self):
        assert detect_structure('I: Loomings\nbody\nII: Carpet-Bag\nbody\nIII: Spouter-Inn\nbody\n')['chapters_detected'] == 3

    def test_lowercase_roman_via_explicit_chapter_word(self):
        text = 'Chapter i. Introduction\nbody\nChapter ii. Methods\nbody\n'
        assert detect_structure(text)['chapters_detected'] == 2

    def test_roman_word_false_positives_rejected(self):
        assert detect_structure('vi: the vim editor\nbody\n')['chapters_detected'] == 0
        assert detect_structure('cli: command line reference\nbody\n')['chapters_detected'] == 0
        assert detect_structure('civ: a civilization primer\nbody\n')['chapters_detected'] == 0
        assert detect_structure('li: a list item\nbody\n')['chapters_detected'] == 0

    def test_roman_word_false_positives_in_markdown_heading(self):
        from book_to_skill.utils import _chapter_number
        assert _chapter_number('## vi: the editor') is not None
        assert _chapter_number('## vi. editor') is not None

class TestCliHelp:

    @pytest.mark.parametrize('flag', ['--help', '-h'])
    def test_help_flag_prints_console_script_usage(self, flag, monkeypatch, capsys):
        monkeypatch.setattr('sys.argv', ['book-to-skill', flag])
        with pytest.raises(SystemExit) as exc_info:
            main()
        captured = capsys.readouterr()
        assert exc_info.value.code == 0
        assert 'Usage: book-to-skill' in captured.err
        assert 'extract.py' not in captured.err
        assert 'Unknown flag' not in captured.err

    def test_no_arguments_keeps_error_exit_with_same_usage(self, monkeypatch, capsys):
        monkeypatch.setattr('sys.argv', ['book-to-skill'])
        with pytest.raises(SystemExit) as exc_info:
            main()
        captured = capsys.readouterr()
        assert exc_info.value.code == 1
        assert 'Usage: book-to-skill' in captured.err
        assert 'extract.py' not in captured.err

class TestParseArgumentsUnknownFlags:

    def test_unknown_flag_warns(self):
        paths, mode, _ = parse_arguments(['extract.py', 'book.pdf', '--mod', 'technical'])
        assert mode == 'text'

    def test_unknown_flag_stderr_message(self):
        import io
        stderr = io.StringIO()
        with mock.patch('sys.stderr', stderr):
            parse_arguments(['extract.py', 'book.pdf', '--unknown-flag'])
        output = stderr.getvalue()
        assert 'WARNING' in output
        assert '--unknown-flag' in output

    def test_known_flags_dont_warn(self, capsys):
        parse_arguments(['extract.py', 'book.pdf', '--mode', 'technical', '--install-missing', 'no'])
        captured = capsys.readouterr()
        assert captured.err == ''

    def test_path_args_not_warned(self, capsys):
        parse_arguments(['extract.py', 'book.pdf', 'notes.txt'])
        captured = capsys.readouterr()
        assert captured.err == ''

class TestCjkTokenEstimate:

    def test_latin_estimate_unchanged(self):
        assert estimate_tokens(' '.join(['word'] * 100)) == 133

    def test_cjk_is_not_undercounted(self):
        assert estimate_tokens('中' * 1500) == 1000

    def test_mixed_latin_and_cjk(self):
        assert estimate_tokens('hello 世界 ' * 100) > 100

    def test_empty_is_zero(self):
        assert estimate_tokens('') == 0

class TestPdfLibsCleanup:

    def test_pypdf_output_is_cleaned(self, monkeypatch):
        pages = [f'HEAD\nsome informa-\ntion page {n}\n{n}' for n in (1, 2, 3)]

        class _Page:

            def __init__(self, t):
                self._t = t

            def extract_text(self):
                return self._t

        class _Reader:

            def __init__(self, f):
                self.pages = [_Page(p) for p in pages]
        import types
        fake = types.SimpleNamespace(PdfReader=_Reader)
        monkeypatch.setitem(sys.modules, 'pypdf', fake)
        monkeypatch.setattr('builtins.open', lambda *a, **k: mock.MagicMock())
        out = pdf_parser.extract_with_pypdf('x.pdf')
        assert 'information' in out
        assert 'HEAD' not in out

    def test_pdfminer_output_is_cleaned(self, monkeypatch):
        raw = '\x0c'.join((f'HEAD\ncon-\ntent page {n}\n{n}' for n in (1, 2, 3)))
        import types
        fake = types.SimpleNamespace(extract_text=lambda path: raw)
        monkeypatch.setitem(sys.modules, 'pdfminer.high_level', fake)
        out = pdf_parser.extract_with_pdfminer('x.pdf')
        assert 'content' in out
        assert 'HEAD' not in out
