import importlib.util
import sys
from pathlib import Path
TOOLS_DIR = Path(__file__).resolve().parent.parent / 'tools'
spec = importlib.util.spec_from_file_location('discovery_tax', TOOLS_DIR / 'discovery_tax.py')
dt = importlib.util.module_from_spec(spec)
sys.modules['discovery_tax'] = dt
spec.loader.exec_module(dt)
SYNTHETIC_BOOK = 'Some Title\nby An Author\n\nSumário\nCapítulo 1 — Foundations\nCapítulo 2 — Mechanisms\nCapítulo 3 — Application\n\nCapítulo 1\n{c1}\n\nCapítulo 2\n{c2}\n\nCapítulo 3\n{c3}\n'.format(c1='foundations ' * 2000, c2='mechanisms ' * 2000, c3='application ' * 2000)

class TestSplitChapters:

    def test_detects_three_chapters(self):
        segs = dt.split_chapters(SYNTHETIC_BOOK)
        chapters = segs[1:]
        assert {c[0] for c in chapters} == {1, 2, 3}

    def test_best_chapter_picks_largest_body_over_toc_line(self):
        text = 'Sumário\nCapítulo 2: Recrutamento\nCapítulo 2\n' + 'conteudo real ' * 50 + '\n'
        chapters = dt.split_chapters(text)[1:]
        heading, body_tok = dt.best_chapter(chapters, 2, dt.count_tokens)
        assert body_tok > 20

    def test_cross_reference_does_not_split(self):
        text = 'Capítulo 1\nbody\nComo vimos no Capítulo 2, isso importa.\nmore body\n'
        segs = dt.split_chapters(text)
        assert len(segs[1:]) == 1

    def test_chapter_with_title_splits(self):
        text = 'Chapter 1. Introduction to AI\nbody\nChapter 2. Foundations\nbody\n'
        chapters = dt.split_chapters(text)[1:]
        assert [c[0] for c in chapters] == [1, 2]

    def test_repeated_cross_ref_does_not_refragment(self):
        text = 'Chapter 1\nbody\nas in Chapter 1, recall\nChapter 2\nbody\n'
        chapters = dt.split_chapters(text)[1:]
        assert [c[0] for c in chapters] == [1, 2]

class TestTocExtraction:

    def test_finds_toc_block(self):
        toc = dt.extract_toc(SYNTHETIC_BOOK.split('Capítulo 1\n')[0])
        assert 'Sumário' in toc
        assert dt.count_tokens(toc) > 0

class TestCountTokens:

    def test_monotonic(self):
        assert dt.count_tokens('a b c d') > dt.count_tokens('a b')

    def test_empty(self):
        assert dt.count_tokens('') == 0

class TestDiscoveryTaxOrdering:

    def test_strategy_ordering(self, tmp_path, capsys):
        book = tmp_path / 'full_text.txt'
        book.write_text(SYNTHETIC_BOOK, encoding='utf-8')
        argv = ['discovery_tax.py', '--full-text', str(book), '--target-chapter', '3', '--core-tokens', '200']
        old = sys.argv
        sys.argv = argv
        try:
            code = dt.main()
        finally:
            sys.argv = old
        out = capsys.readouterr().out
        assert code == 0

        def grab(label):
            for line in out.splitlines():
                if label in line:
                    nums = [int(x.replace(',', '')) for x in __import__('re').findall('[\\d,]+', line) if x.strip(',')]
                    return nums[0]
            raise AssertionError(f'label not found: {label}')
        dump = grab('context-dump')
        d_best = grab('discovery (best)')
        d_loop = grab('discovery (loop)')
        skill = grab('book-to-skill')
        assert skill < d_best < dump, (skill, d_best, dump)
        assert d_best <= d_loop, (d_best, d_loop)
        assert skill < d_loop

def test_extract_toc_detects_non_english_toc():
    front = 'Cover junk\nlots of preamble\n\nInhaltsverzeichnis\nKapitel 1 .. 5\nKapitel 2 .. 9\n'
    toc = dt.extract_toc(front)
    assert toc.lstrip().startswith('Inhaltsverzeichnis')
    assert len(toc) < len(front)
