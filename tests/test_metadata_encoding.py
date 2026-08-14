import json
import sys
from pathlib import Path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))
from book_to_skill.utils import main

class TestMetadataOutputEncoding:
    CJK_SOURCE = '第一章 緒論\n\nBody one.\n\n第二章 架構\n\nBody two.\n'

    def _run_main(self, tmp_path, monkeypatch):
        source = tmp_path / 'cjk.md'
        source.write_text(self.CJK_SOURCE, encoding='utf-8')
        out_dir = tmp_path / 'output'
        out_meta = out_dir / 'metadata.json'
        monkeypatch.setenv('BOOK_SKILL_WORKDIR', str(out_dir))
        monkeypatch.setattr('book_to_skill.utils.OUTPUT_DIR', out_dir)
        monkeypatch.setattr('book_to_skill.utils.OUTPUT_TEXT', out_dir / 'full_text.txt')
        monkeypatch.setattr('book_to_skill.utils.OUTPUT_META', out_meta)
        monkeypatch.setattr('book_to_skill.utils.prepare_dependencies', lambda *a: None)
        monkeypatch.setattr('sys.argv', ['extract.py', str(source), '--install-missing', 'no'])
        main()
        return out_meta

    def test_metadata_write_declares_utf8(self, tmp_path, monkeypatch):
        captured = {}
        original_write_text = Path.write_text

        def recording_write_text(self, data, encoding=None, **kwargs):
            if self.name == 'metadata.json':
                captured['encoding'] = encoding
            return original_write_text(self, data, encoding=encoding, **kwargs)
        monkeypatch.setattr(Path, 'write_text', recording_write_text)
        self._run_main(tmp_path, monkeypatch)
        assert captured.get('encoding') == 'utf-8', 'metadata.json was written with the locale encoding; it must declare encoding="utf-8" because the JSON is dumped with ensure_ascii=False'

    def test_non_ascii_headings_round_trip_as_utf8(self, tmp_path, monkeypatch):
        out_meta = self._run_main(tmp_path, monkeypatch)
        meta = json.loads(out_meta.read_bytes().decode('utf-8'))
        assert meta['chapters_detected'] == 2
        assert '第一章 緒論' in meta['chapter_headings_sample']
        assert '第二章 架構' in meta['chapter_headings_sample']

    def test_metadata_is_valid_utf8_on_disk(self, tmp_path, monkeypatch):
        out_meta = self._run_main(tmp_path, monkeypatch)
        raw = out_meta.read_bytes()
        decoded = raw.decode('utf-8')
        assert '第一章' in decoded
        assert '第一章 緒論'.encode('utf-8') in raw
