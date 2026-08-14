import sys
from pathlib import Path
import pytest
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))
from book_to_skill.config import CJK_CHARS_PER_TOKEN
from book_to_skill.utils import estimate_tokens
BMP = '一二三四五六七八九十'
SIP = '𠀀𠀁𪜀𫝀𬺰'

class TestSupplementaryPlaneCounted:

    def test_sip_matches_bmp_for_the_same_length(self):
        bmp_text = BMP * 200
        sip_text = SIP * 400
        assert len(bmp_text) == len(sip_text)
        assert estimate_tokens(sip_text) == estimate_tokens(bmp_text)

    def test_sip_only_text_is_not_one_token(self):
        text = SIP * 400
        assert estimate_tokens(text) > 1000

    def test_estimate_tracks_the_configured_ratio(self):
        text = SIP * 400
        assert estimate_tokens(text) == pytest.approx(len(text) / CJK_CHARS_PER_TOKEN, rel=0.01)

    def test_mixed_plane_text_is_consistent(self):
        mixed = BMP * 180 + SIP * 40
        all_bmp = BMP * 200
        assert len(mixed) == len(all_bmp)
        assert estimate_tokens(mixed) == estimate_tokens(all_bmp)

    @pytest.mark.parametrize('codepoint, name', [(131072, 'Ext B start'), (173791, 'Ext B end'), (173824, 'Ext C start'), (177984, 'Ext D start'), (183984, 'Ext E start'), (191472, 'Ext I start'), (196608, 'Ext G start'), (201550, 'Ext G end'), (201552, 'Ext H start'), (205743, 'Ext H end')])
    def test_extension_ranges_are_covered(self, codepoint, name):
        text = chr(codepoint) * 300
        assert estimate_tokens(text) > 100, name

class TestExistingBehaviourPreserved:

    def test_bmp_cjk_unchanged(self):
        text = BMP * 200
        assert estimate_tokens(text) == pytest.approx(len(text) / CJK_CHARS_PER_TOKEN, rel=0.01)

    @pytest.mark.parametrize('sample', ['第一章 緒論', '제1장 총칙', 'こんにちは世界', '你好世界'])
    def test_short_cjk_samples_still_counted(self, sample):
        assert estimate_tokens(sample) >= 1

    def test_latin_text_unaffected(self):
        text = 'the quick brown fox jumps over the lazy dog ' * 100
        assert estimate_tokens(text) == int(len(text.split()) / 0.75)

    def test_empty_text(self):
        assert estimate_tokens('') == 0

    def test_latin_with_a_single_sip_character(self):
        text = 'word ' * 100 + '𠀀'
        assert 120 < estimate_tokens(text) < 145

class TestNonCjkSupplementaryPlanesExcluded:

    @pytest.mark.parametrize('char, name', [('😀', 'emoji'), ('𝐀', 'math bold capital A'), ('🇦', 'regional indicator')])
    def test_astral_non_cjk_takes_the_word_branch(self, char, name):
        assert estimate_tokens(char * 300) == 1, name
