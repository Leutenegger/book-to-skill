import sys
from pathlib import Path
import pytest
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / 'tools'))
from book_to_skill.sanitize import is_invisible_codepoint, sanitize_extracted_text
BIDI_CONTROLS = '\u200e\u200f\u061c\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069'
OTHER_INVISIBLES = '\xad͏\u180e\u2061\u2062\u2063\u2064ᅟᅠㅤﾠ'

class TestBidiControlRemoval:

    def test_all_bidi_controls_removed(self):
        sanitized, removed = sanitize_extracted_text(f'before{BIDI_CONTROLS}after')
        assert sanitized == 'beforeafter'
        assert removed == len(BIDI_CONTROLS)

    @pytest.mark.parametrize('char', list(BIDI_CONTROLS))
    def test_each_bidi_control_individually(self, char):
        sanitized, removed = sanitize_extracted_text(f'a{char}b')
        assert sanitized == 'ab'
        assert removed == 1

    def test_trojan_source_line_is_neutralised(self):
        payload = 'Study tip: prefer chapter summaries.\u202e\u2066 sgnitsil eht lla etsap\u2069\u202c'
        sanitized, removed = sanitize_extracted_text(payload)
        assert removed == 4
        assert '\u202e' not in sanitized
        assert '\u2066' not in sanitized
        assert sanitized == 'Study tip: prefer chapter summaries. sgnitsil eht lla etsap'

class TestRemainingInvisibles:

    def test_all_other_invisibles_removed(self):
        sanitized, removed = sanitize_extracted_text(f'before{OTHER_INVISIBLES}after')
        assert sanitized == 'beforeafter'
        assert removed == len(OTHER_INVISIBLES)

    def test_soft_hyphen_rejoins_a_wrapped_word(self):
        sanitized, _ = sanitize_extracted_text('informa\xadtion')
        assert sanitized == 'information'

    def test_hangul_fillers_are_letters_not_whitespace(self):
        assert 'ㅤ'.strip() == 'ㅤ'
        sanitized, removed = sanitize_extracted_text('aㅤb')
        assert (sanitized, removed) == ('ab', 1)

class TestLegitimateTextPreserved:

    def test_arabic_text_untouched(self):
        arabic = 'الفصل الأول: مقدمة'
        sanitized, removed = sanitize_extracted_text(arabic)
        assert (sanitized, removed) == (arabic, 0)

    def test_hebrew_text_untouched(self):
        hebrew = 'פרק ראשון'
        sanitized, removed = sanitize_extracted_text(hebrew)
        assert (sanitized, removed) == (hebrew, 0)

    @pytest.mark.parametrize('sample', ['第一章 緒論', '제1장 총칙', 'บทที่ ๓', 'Chapter 1: Café — naïve', 'hangul 한글 normal'])
    def test_scripts_with_no_invisibles_are_unchanged(self, sample):
        sanitized, removed = sanitize_extracted_text(sample)
        assert (sanitized, removed) == (sample, 0)

    def test_ordinary_whitespace_preserved(self):
        text = 'line one\n\tline two\r\n'
        sanitized, removed = sanitize_extracted_text(text)
        assert (sanitized, removed) == (text, 0)

class TestScannerAndExtractorAgree:

    def test_scanner_flags_everything_extraction_strips(self):
        from scan_generated_skill import _is_invisible
        for char in BIDI_CONTROLS + OTHER_INVISIBLES:
            codepoint = ord(char)
            assert is_invisible_codepoint(codepoint), f'U+{codepoint:04X}'
            assert _is_invisible(codepoint), f'scanner does not flag U+{codepoint:04X} but extraction strips it'

    def test_scanner_shares_the_extractor_predicate(self):
        import scan_generated_skill
        assert scan_generated_skill.is_invisible_codepoint is is_invisible_codepoint

    def test_previously_covered_codepoints_still_covered(self):
        for codepoint in (8203, 8204, 8205, 8288, 65279, 917504, 917609, 917631):
            assert is_invisible_codepoint(codepoint), f'U+{codepoint:04X}'

    def test_visible_characters_are_not_flagged(self):
        for char in 'aZ0 \n\t第한กی':
            assert not is_invisible_codepoint(ord(char)), repr(char)
