import html
import re
import sys
from book_to_skill.parsers.text import read_text_file
from book_to_skill.exceptions import ExtractionError
_RTF_UNICODE = re.compile("\\\\u(-?\\d+)[ ]?(?:\\\\'[0-9a-fA-F]{2}|\\?)?")

def _rtf_unicode_repl(match: re.Match) -> str:
    cp = int(match.group(1)) % 65536
    if cp == 0 or 55296 <= cp <= 57343:
        return ''
    return chr(cp)
_SKIP_DESTINATIONS = frozenset({'fonttbl', 'colortbl', 'stylesheet', 'info', 'listtable', 'listoverridetable', 'revtbl', 'rsidtbl', 'latentstyles', 'datastore', 'themedata', 'colorschememapping', 'filetbl', 'xmlnstbl', 'pgptbl', 'protusertbl', 'userprops', 'docvar', 'pict', 'objdata', 'bkmkstart', 'bkmkend'})
_GROUP_DESTINATION = re.compile('\\\\\\*?\\\\?([a-zA-Z]+)')

def _strip_destination_groups(raw: str) -> str:
    out: list[str] = []
    index = 0
    depth = 0
    skip_at_depth = 0
    length = len(raw)
    while index < length:
        char = raw[index]
        if char == '\\' and index + 1 < length and (raw[index + 1] in '{}\\'):
            if not skip_at_depth:
                out.append(raw[index:index + 2])
            index += 2
            continue
        if char == '{':
            depth += 1
            if not skip_at_depth:
                match = _GROUP_DESTINATION.match(raw, index + 1)
                ignorable = raw.startswith('{\\*', index)
                if ignorable or (match and match.group(1) in _SKIP_DESTINATIONS):
                    skip_at_depth = depth
                else:
                    out.append(char)
            index += 1
            continue
        if char == '}':
            if skip_at_depth and depth == skip_at_depth:
                skip_at_depth = 0
            elif not skip_at_depth:
                out.append(char)
            depth -= 1
            index += 1
            continue
        if not skip_at_depth:
            out.append(char)
        index += 1
    if skip_at_depth:
        return raw
    return ''.join(out)

def strip_rtf_fallback(raw: str) -> str:
    raw = _strip_destination_groups(raw)
    raw = _RTF_UNICODE.sub(_rtf_unicode_repl, raw)
    raw = re.sub("\\\\'[0-9a-fA-F]{2}", ' ', raw)
    raw = re.sub('\\\\par[d]?', '\n', raw)
    raw = re.sub('\\\\tab', '\t', raw)
    raw = raw.replace('\\\\', '\x01').replace('\\{', '\x02').replace('\\}', '\x03')
    raw = re.sub('\\\\[a-zA-Z]+-?\\d* ?', '', raw)
    raw = raw.replace('{', '').replace('}', '')
    raw = raw.replace('\x01', '\\').replace('\x02', '{').replace('\x03', '}')
    return html.unescape(raw)

def extract_rtf(rtf_path: str) -> tuple[str, str]:
    raw = read_text_file(rtf_path)
    if raw is None:
        raise ExtractionError(f'Could not read RTF file: {rtf_path}')
    try:
        from striprtf.striprtf import rtf_to_text
        text = rtf_to_text(raw)
        if text.strip():
            return (text, 'striprtf')
    except ImportError:
        pass
    except Exception as e:
        print(f'  [warn] extract_rtf/striprtf failed: {type(e).__name__}: {e}', file=sys.stderr)
    return (strip_rtf_fallback(raw), 'rtf-regex')
