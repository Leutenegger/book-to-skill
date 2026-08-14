import sys
from pathlib import Path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))
from book_to_skill.utils import _closed_fence_line_numbers, _structural_chapter_count
SECTIONS = ['## Getting Started\nInstall the toolchain.\n', '## Configuration\nEdit the config file.\n', '## Writing Markdown\nA fenced block looks like this:\n', '## Deployment\nShip it.\n', '## Monitoring\nWatch the dashboards.\n', '## Scaling\nAdd replicas.\n', '## Security\nRotate credentials.\n', '## Troubleshooting\nRead the logs.\n']

def _book(third_section_tail: str) -> str:
    body = list(SECTIONS)
    body[2] = body[2] + third_section_tail
    return '# The Handbook\n\n' + '\n'.join(body)

class TestUnbalancedFenceDoesNotSwallowHeadings:

    def test_unclosed_backtick_fence_keeps_later_sections(self):
        broken = _book('\n```\nnot closed\n')
        assert _structural_chapter_count(broken) == 8

    def test_matches_the_balanced_document(self):
        balanced = _book('\n```\nclosed\n```\n')
        broken = _book('\n```\nnot closed\n')
        assert _structural_chapter_count(broken) == _structural_chapter_count(balanced)

    def test_unclosed_tilde_fence_keeps_later_sections(self):
        text = '# Book\n\n## Alpha\na\n\n~~~\n\n## Beta\nb\n\n## Gamma\nc\n'
        assert _structural_chapter_count(text) == 3

    def test_trailing_lone_fence_marker(self):
        text = '# Book\n\n## Alpha\na\n\n## Beta\nb\n\n```\n'
        assert _structural_chapter_count(text) == 2

class TestBalancedFencesStillSuppressHeadings:

    def test_heading_inside_a_closed_fence_is_not_counted(self):
        text = '# Book\n\n## Alpha\na\n\n```sh\n# Not a heading\n## Also not a heading\n```\n\n## Beta\nb\n'
        assert _structural_chapter_count(text) == 2

    def test_multiple_closed_fences(self):
        text = '# Book\n\n## Alpha\n```\n## fake one\n```\n\n## Beta\n```\n## fake two\n```\n\n## Gamma\nreal\n'
        assert _structural_chapter_count(text) == 3

    def test_setext_heading_inside_a_closed_fence_is_not_counted(self):
        text = '# Book\n\n## Alpha\na\n\n```\nFake Title\n==========\n```\n\n## Beta\nb\n'
        assert _structural_chapter_count(text) == 2

    def test_tilde_fence_suppresses_when_closed(self):
        text = '# Book\n\n## Alpha\na\n\n~~~\n## fake\n~~~\n\n## Beta\nb\n'
        assert _structural_chapter_count(text) == 2

class TestFenceCharacterMustMatch:

    def test_backtick_fence_not_closed_by_tilde(self):
        lines = ['```', 'code', '~~~', 'more code']
        assert _closed_fence_line_numbers(lines) == set()

    def test_matching_pair_is_detected(self):
        lines = ['before', '```', 'code', '```', 'after']
        assert _closed_fence_line_numbers(lines) == {1, 2, 3}

    def test_longer_fence_markers(self):
        lines = ['````', 'code with ``` inside', '````']
        assert _closed_fence_line_numbers(lines) == {0, 1, 2}

    def test_no_fences_at_all(self):
        assert _closed_fence_line_numbers(['a', 'b', 'c']) == set()

    def test_indented_fence_is_recognised(self):
        lines = ['  ```', 'code', '  ```']
        assert _closed_fence_line_numbers(lines) == {0, 1, 2}

class TestAcceptedOverCountCost:
    HELP_OUTPUT_IN_UNCLOSED_FENCE = '# Handbook\n\n## Alpha\na\n\n## Beta\n```\n$ tool --help\nOptions\n-------\nmore code\n\n## Gamma\ng\n\n## Delta\nd\n'

    def test_over_counts_by_one_setext_promotion(self):
        assert _structural_chapter_count(self.HELP_OUTPUT_IN_UNCLOSED_FENCE) == 5

    def test_every_real_section_survives(self):
        assert _structural_chapter_count(self.HELP_OUTPUT_IN_UNCLOSED_FENCE) >= 4

    def test_same_document_with_the_fence_closed_is_exact(self):
        closed = self.HELP_OUTPUT_IN_UNCLOSED_FENCE.replace('more code\n\n', 'more code\n```\n\n')
        assert _structural_chapter_count(closed) == 4

class TestExistingBehaviourPreserved:

    def test_bare_digit_titles_still_rejected(self):
        text = '# Book\n\n## 5 Setup\na\n\n## 6 Teardown\nb\n\n## Real One\nc\n'
        assert _structural_chapter_count(text) == 2

    def test_setext_headings_still_counted(self):
        text = 'Alpha\n=====\n\ntext\n\nBeta\n====\n\ntext\n'
        assert _structural_chapter_count(text) == 2

    def test_document_with_no_headings(self):
        assert _structural_chapter_count('just prose\nmore prose\n') == 0
