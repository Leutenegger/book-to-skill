#!/usr/bin/env python3
from __future__ import annotations
import argparse
import re
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from book_to_skill.utils import _chapter_number as chapter_number, _TOC_PATTERN as toc_pattern

def count_tokens(text: str) -> int:
    try:
        import tiktoken
        enc = tiktoken.get_encoding('cl100k_base')
        return len(enc.encode(text))
    except Exception:
        return int(len(text.split()) / 0.75)

def token_method() -> str:
    try:
        import tiktoken
        return 'tiktoken cl100k_base (real BPE)'
    except Exception:
        return 'words/0.75 heuristic (tiktoken not installed)'

def split_chapters(text: str) -> list[tuple[int | None, str, str]]:
    lines = text.splitlines()
    segments: list[tuple[int | None, str, list[str]]] = [(None, '__front__', [])]
    for line in lines:
        num = chapter_number(line)
        if num is not None:
            segments.append((num, line.strip(), []))
        segments[-1][2].append(line)
    return [(n, h, '\n'.join(b)) for n, h, b in segments]

def best_chapter(chapters: list[tuple[int | None, str, str]], n: int, tok) -> tuple[str, int] | None:
    cands = [(h, tok(b)) for num, h, b in chapters if num == n]
    return max(cands, key=lambda x: x[1]) if cands else None

def extract_toc(front_matter: str) -> str:
    m = toc_pattern.search(front_matter)
    if not m:
        return front_matter
    return front_matter[m.start():]

def main() -> int:
    ap = argparse.ArgumentParser(description='Measure the Discovery Loop Tax on a real book.')
    ap.add_argument('--full-text', required=True, help='extractor full_text.txt')
    ap.add_argument('--skill-dir', help='generated skill folder (for SKILL.md + chapter sizes)')
    ap.add_argument('--target-chapter', type=int, default=5, help='1-based chapter index the question is about')
    ap.add_argument('--core-tokens', type=int, default=4000, help='resident SKILL.md core size if --skill-dir not given (design cap)')
    args = ap.parse_args()
    full_text = Path(args.full_text).read_text(encoding='utf-8', errors='ignore')
    total = count_tokens(full_text)
    segs = split_chapters(full_text)
    front = segs[0][2]
    chapters = segs[1:]
    if not chapters:
        print('No chapters detected — cannot model discovery. The source may be a\ntechnical PDF whose headings were flattened by text extraction; try\ntechnical mode (Docling) so chapter structure is preserved.', file=sys.stderr)
        return 1
    toc = extract_toc(front)
    toc_tok = count_tokens(toc)
    distinct = sorted({num for num, _, _ in chapters if num is not None})
    n = args.target_chapter
    best = best_chapter(chapters, n, count_tokens)
    if best is None:
        n = distinct[min(n - 1, len(distinct) - 1)] if distinct else n
        best = best_chapter(chapters, n, count_tokens)
    target_heading, target_raw = best
    prior = best_chapter(chapters, n - 1, count_tokens)
    prior_raw = prior[1] if prior else 0
    if args.skill_dir:
        sd = Path(args.skill_dir)
        skill_md = sd / 'SKILL.md'
        core = count_tokens(skill_md.read_text(encoding='utf-8')) if skill_md.exists() else args.core_tokens
        chs = sorted((sd / 'chapters').glob('*.md')) if (sd / 'chapters').is_dir() else []
        comp_chapter = None
        for c in chs:
            if re.search(f'ch0*{n}\\b', c.name):
                comp_chapter = count_tokens(c.read_text(encoding='utf-8'))
                break
        if comp_chapter is None and chs:
            comp_chapter = sum((count_tokens(c.read_text(encoding='utf-8')) for c in chs)) // len(chs)
        comp_chapter = comp_chapter or 1000
        core_label = 'measured SKILL.md' if skill_md.exists() else 'design cap'
    else:
        core = args.core_tokens
        comp_chapter = 1000
        core_label = 'design cap (no --skill-dir)'
    dump = total
    skill = core + comp_chapter
    disc_best = toc_tok + target_raw
    disc_loop = toc_tok + target_raw + prior_raw

    def ratio(a: int, b: int) -> str:
        return f'{a / b:.1f}x' if b else 'n/a'
    print('Discovery Loop Tax — measured on a real book\n')
    print(f'  token method : {token_method()}')
    print(f'  source       : {Path(args.full_text).name}')
    print(f'  chapters      : {len(distinct)} detected')
    print(f'  target        : chapter {n}  ({target_heading[:60]})')
    print(f'  book total    : {total:,} tokens\n')
    print('  Cost to answer ONE targeted question (tokens entering context):\n')
    print(f'    context-dump      : {dump:>9,}   (resident, re-billed EVERY turn)')
    print(f'    discovery (best)  : {disc_best:>9,}   ToC ({toc_tok:,}) + raw target chapter ({target_raw:,})')
    print(f'    discovery (loop)  : {disc_loop:>9,}   + 1 prior chapter for a missing definition ({prior_raw:,})')
    print(f'    book-to-skill     : {skill:>9,}   core [{core_label}] ({core:,}) + compiled chapter ({comp_chapter:,})\n')
    print('  book-to-skill advantage:')
    print(f'    vs context-dump   : {ratio(dump, skill)} fewer tokens')
    print(f'    vs discovery best : {ratio(disc_best, skill)} fewer tokens')
    print(f'    vs discovery loop : {ratio(disc_loop, skill)} fewer tokens')
    print("\n  Note: the discovery figures are a model using the book's real ToC/chapter")
    print('  sizes; a single read, not a recurring cost. context-dump recurs every turn.')
    return 0
if __name__ == '__main__':
    sys.exit(main())
