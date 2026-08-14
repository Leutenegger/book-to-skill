import sys
from pathlib import Path
import pytest
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))
from book_to_skill.parsers.rtf import strip_rtf_fallback
FULL_HEADER_RTF = '{\\rtf1\\ansi\\ansicpg1252\\deff0\n{\\fonttbl{\\f0\\fnil\\fcharset0 Calibri;}{\\f1\\fswiss Helvetica Neue;}}\n{\\colortbl;\\red255\\green0\\blue0;\\red0\\green0\\blue255;}\n{\\stylesheet{\\s0\\snext0 Normal;}{\\s1\\sbasedon0 heading 1;}}\n{\\*\\generator Riched20 10.0.19041;}\n{\\info{\\title Secret Draft}{\\author Jane Roe}}\n\\pard\\f0\\fs24 Chapter 1\\par\nReal body text here.\\par}'
LEAK_PROBES = ['Calibri', 'Helvetica Neue', 'Normal', 'heading 1', 'Riched20', 'Secret Draft', 'Jane Roe']

class TestDestinationGroupsDropped:

    @pytest.mark.parametrize('probe', LEAK_PROBES)
    def test_probe_does_not_leak(self, probe):
        assert probe not in strip_rtf_fallback(FULL_HEADER_RTF)

    def test_body_text_survives(self):
        out = strip_rtf_fallback(FULL_HEADER_RTF)
        assert 'Chapter 1' in out
        assert 'Real body text here.' in out

    def test_chapter_heading_is_on_its_own_line(self):
        lines = [ln for ln in strip_rtf_fallback(FULL_HEADER_RTF).splitlines() if ln.strip()]
        assert lines[0].strip() == 'Chapter 1'

    def test_info_metadata_not_exposed(self):
        rtf = '{\\rtf1{\\info{\\title Confidential}{\\author A. Person}}Body.\\par}'
        out = strip_rtf_fallback(rtf)
        assert out.strip() == 'Body.'

    def test_pict_binary_payload_dropped(self):
        rtf = '{\\rtf1{\\pict\\wmetafile8 0102030405060708090a0b0c}Caption here.\\par}'
        out = strip_rtf_fallback(rtf)
        assert '0102030405' not in out
        assert 'Caption here.' in out

    def test_nested_group_inside_skipped_group(self):
        rtf = '{\\rtf1 {\\stylesheet{\\s1\\sbasedon0{\\*\\ud junk}heading 1;}}Body.\\par}'
        out = strip_rtf_fallback(rtf)
        assert 'heading 1' not in out
        assert 'junk' not in out
        assert 'Body.' in out

    def test_content_group_after_skipped_group_is_kept(self):
        rtf = '{\\rtf1{\\fonttbl{\\f0 Arial;}}{\\b Bold text}\\par tail\\par}'
        out = strip_rtf_fallback(rtf)
        assert 'Arial' not in out
        assert 'Bold text' in out
        assert 'tail' in out

class TestIgnorableDestinations:

    def test_unknown_star_destination_skipped(self):
        rtf = '{\\rtf1{\\*\\somevendorext payload text}Body.\\par}'
        out = strip_rtf_fallback(rtf)
        assert 'payload text' not in out
        assert 'Body.' in out

    def test_field_keeps_result_drops_instruction(self):
        rtf = '{\\rtf1 See {\\field{\\*\\fldinst HYPERLINK bm1}{\\fldrslt chapter 4}} now.\\par}'
        out = strip_rtf_fallback(rtf)
        assert 'HYPERLINK' not in out
        assert 'See chapter 4 now.' in out.replace('\n', ' ')

class TestEscapedLiteralsSurvive:

    def test_escaped_braces_become_literal_braces(self):
        out = strip_rtf_fallback('{\\rtf1 A set \\{a, b\\} of items.\\par}')
        assert '{a, b}' in out

    def test_escaped_backslash_preserved(self):
        out = strip_rtf_fallback('{\\rtf1 Path C:\\\\temp\\\\out\\par}')
        assert 'C:\\temp\\out' in out

class TestExistingBehaviourPreserved:
    _BS = '\\'

    def test_unicode_escapes_still_decode(self):
        text = '{\\rtf1{\\fonttbl{\\f0 Arial;}}' + self._BS + 'u8220' + self._BS + "'93Hi" + self._BS + 'u8221' + self._BS + "'94" + '\\par}'
        out = strip_rtf_fallback(text)
        assert '“Hi”' in out
        assert 'Arial' not in out

    def test_par_and_tab_still_convert(self):
        out = strip_rtf_fallback('{\\rtf1 a\\par b\\tab c}')
        assert '\n' in out
        assert '\t' in out

class TestMalformedInputIsNotTruncated:

    def test_unterminated_skipped_group_falls_back(self):
        rtf = '{\\rtf1{\\fonttbl{\\f0 Arial; Body text never closed'
        out = strip_rtf_fallback(rtf)
        assert 'Body text never closed' in out
