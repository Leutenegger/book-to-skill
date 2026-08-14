import subprocess
from pathlib import Path
import pytest
REPO_ROOT = Path(__file__).resolve().parent.parent

def _git(*args: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(['git', *args], cwd=REPO_ROOT, capture_output=True, timeout=30, text=True, encoding='utf-8', errors='surrogateescape')
    except (OSError, subprocess.SubprocessError) as exc:
        pytest.skip(f'git unavailable: {exc}')

def _tracked_files() -> list[str]:
    toplevel = _git('rev-parse', '--show-toplevel')
    if toplevel.returncode != 0:
        pytest.skip('not a git checkout (e.g. installed sdist)')
    if Path(toplevel.stdout.strip()).resolve() != REPO_ROOT:
        pytest.skip('REPO_ROOT is not the root of the enclosing git repository')
    listed = _git('ls-files', '-z')
    if listed.returncode != 0:
        pytest.skip('not a git checkout (e.g. installed sdist)')
    return [path for path in listed.stdout.split('\x00') if path]

def test_no_compiled_bytecode_is_tracked():
    offenders = [path for path in _tracked_files() if path.endswith('.pyc') or '__pycache__/' in path]
    assert offenders == [], 'compiled bytecode is tracked in git: ' + ', '.join(offenders) + ' — remove with `git rm --cached <path>`'
