import os
import stat
import sys
from pathlib import Path
import pytest
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))
from book_to_skill.exceptions import ExtractionError
from book_to_skill.utils import extract_single_file, main

def _make_unreadable(path: Path) -> Path:
    path.write_bytes(b'junk')
    path.chmod(0)
    return path
skip_if_readable_anyway = pytest.mark.skipif(os.geteuid() == 0 if hasattr(os, 'geteuid') else True, reason='root (or a platform without POSIX permissions) can read mode-000 files')

@skip_if_readable_anyway
def test_unreadable_unknown_suffix_raises_extraction_error(tmp_path):
    bad = _make_unreadable(tmp_path / 'mystery.dat')
    try:
        with pytest.raises(ExtractionError) as excinfo:
            extract_single_file(bad, 'text', 'no')
        assert 'mystery.dat' in str(excinfo.value)
    finally:
        bad.chmod(stat.S_IRUSR | stat.S_IWUSR)

@skip_if_readable_anyway
def test_batch_survives_unreadable_source(tmp_path, monkeypatch, capsys):
    bad = _make_unreadable(tmp_path / 'mystery.dat')
    good = tmp_path / 'ok.md'
    good.write_text('Chapter 1\nReal content.\n', encoding='utf-8')
    workdir = tmp_path / 'work'
    monkeypatch.setenv('BOOK_SKILL_WORKDIR', str(workdir))
    import book_to_skill.config as config
    import book_to_skill.utils as utils
    for module in (config, utils):
        monkeypatch.setattr(module, 'OUTPUT_DIR', workdir, raising=False)
        monkeypatch.setattr(module, 'OUTPUT_TEXT', workdir / 'full_text.txt', raising=False)
        monkeypatch.setattr(module, 'OUTPUT_META', workdir / 'metadata.json', raising=False)
    monkeypatch.setattr(sys, 'argv', ['extract.py', str(bad), str(good), '--mode', 'text', '--install-missing', 'no'])
    try:
        main()
    finally:
        bad.chmod(stat.S_IRUSR | stat.S_IWUSR)
    text = (workdir / 'full_text.txt').read_text(encoding='utf-8')
    assert 'Real content.' in text
    out = capsys.readouterr()
    combined = out.out + out.err
    assert 'mystery.dat' in combined
    assert 'Skipping' in combined or 'skipped' in combined

def test_missing_file_still_reports_not_found(tmp_path):
    with pytest.raises(ExtractionError) as excinfo:
        extract_single_file(tmp_path / 'nope.dat', 'text', 'no')
    assert 'File not found' in str(excinfo.value)

def test_readable_unknown_suffix_still_rejected_by_format(tmp_path):
    odd = tmp_path / 'mystery.dat'
    odd.write_bytes(b'not a pdf or a zip')
    with pytest.raises(ExtractionError) as excinfo:
        extract_single_file(odd, 'text', 'no')
    assert 'Unsupported format' in str(excinfo.value)
