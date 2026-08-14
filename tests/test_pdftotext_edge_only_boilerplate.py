import sys
from pathlib import Path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))
from book_to_skill.parsers.pdf import clean_pdftotext

class TestBoilerplateRemovalIsEdgeOnly:
    HEADER_MATCHES_HEADING = '\x0c'.join(['Reliability\nOpening discussion of the topic.\n42', 'Reliability\nMore body text on page two.\n43', 'Reliability\nStill more body text on page three.\n44', 'Reliability\nEnd of the previous section.\nReliability\nThis section explains the term properly.\n45'])

    def test_mid_page_heading_survives(self):
        out = clean_pdftotext(self.HEADER_MATCHES_HEADING)
        assert out.count('Reliability') == 1

    def test_surrounding_body_text_intact(self):
        out = clean_pdftotext(self.HEADER_MATCHES_HEADING)
        assert 'This section explains the term properly.' in out
        assert 'End of the previous section.' in out

    def test_running_headers_are_still_removed(self):
        out = clean_pdftotext(self.HEADER_MATCHES_HEADING)
        assert not out.startswith('Reliability')
        assert out.splitlines()[0] == 'Opening discussion of the topic.'

    def test_page_numbers_are_still_removed(self):
        out = clean_pdftotext(self.HEADER_MATCHES_HEADING)
        assert not any((str(n) in out for n in (42, 43, 44, 45)))

    def test_plain_running_header_still_stripped(self):
        raw = '\x0c'.join(['DESIGNING SYSTEMS\nBody one.', 'DESIGNING SYSTEMS\nBody two.', 'DESIGNING SYSTEMS\nBody three.'])
        out = clean_pdftotext(raw)
        assert 'DESIGNING SYSTEMS' not in out
        assert 'Body one.' in out and 'Body three.' in out

    def test_footer_boilerplate_still_stripped(self):
        raw = '\x0c'.join(["Body one.\nO'Reilly Media", "Body two.\nO'Reilly Media", "Body three.\nO'Reilly Media"])
        out = clean_pdftotext(raw)
        assert "O'Reilly Media" not in out
        assert 'Body two.' in out

class TestSingleLinePageVoting:

    def test_part_divider_page_is_not_stripped(self):
        raw = '\x0c'.join(['PART ONE', 'Chapter 1\nBody text of the first chapter.', 'PART ONE', 'Chapter 2\nBody text of the second chapter.'])
        out = clean_pdftotext(raw)
        assert out.count('PART ONE') == 2

    def test_genuinely_repeated_single_line_page_still_stripped(self):
        raw = '\x0c'.join(['NOTICE'] * 3 + ['Chapter 1\nReal body text.'])
        out = clean_pdftotext(raw)
        assert 'NOTICE' not in out
        assert 'Real body text.' in out

class TestExistingBehaviourPreserved:

    def test_hyphenated_wrap_still_rejoined(self):
        assert 'information' in clean_pdftotext('informa-\ntion is here')

    def test_short_document_keeps_content_and_drops_form_feeds(self):
        out = clean_pdftotext('Page one text.\x0cPage two text.')
        assert 'Page one text.' in out and 'Page two text.' in out
        assert '\x0c' not in out

    def test_mid_page_bare_number_is_kept(self):
        raw = '\x0c'.join(['Intro line.\n7\nMore text after the number.\n1', 'Second page.\n2', 'Third page.\n3'])
        out = clean_pdftotext(raw)
        assert '7' in out

    def test_one_word_lines_still_survive(self):
        raw = '\x0c'.join(['Body one.\nCIVIL', 'Body two.\nMIX', 'Body three.\nVIVID'])
        out = clean_pdftotext(raw)
        for word in ('CIVIL', 'MIX', 'VIVID'):
            assert word in out, word

    def test_roman_front_matter_numbers_still_stripped(self):
        raw = '\x0c'.join(['Preface text one.\niv', 'Preface text two.\nv', 'Preface text three.\nvi'])
        out = clean_pdftotext(raw)
        assert 'Preface text one.' in out
        assert [ln for ln in out.splitlines() if ln.strip() in ('iv', 'v', 'vi')] == []
