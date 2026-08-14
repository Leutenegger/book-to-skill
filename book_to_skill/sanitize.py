from __future__ import annotations
_ZERO_WIDTH_CODEPOINTS = frozenset({8203, 8204, 8205, 8288, 65279, 173, 847, 6158, 8289, 8290, 8291, 8292})
_BIDI_CONTROL_CODEPOINTS = frozenset({8206, 8207, 1564, 8234, 8235, 8236, 8237, 8238, 8294, 8295, 8296, 8297})
_INVISIBLE_LETTER_CODEPOINTS = frozenset({4447, 4448, 12644, 65440})
_INVISIBLE_CODEPOINTS = _ZERO_WIDTH_CODEPOINTS | _BIDI_CONTROL_CODEPOINTS | _INVISIBLE_LETTER_CODEPOINTS
_TAG_BLOCK_START = 917504
_TAG_BLOCK_END = 917631

def is_invisible_codepoint(codepoint: int) -> bool:
    return codepoint in _INVISIBLE_CODEPOINTS or _TAG_BLOCK_START <= codepoint <= _TAG_BLOCK_END

def sanitize_extracted_text(text: str) -> tuple[str, int]:
    kept: list[str] = []
    removed = 0
    for character in text:
        if is_invisible_codepoint(ord(character)):
            removed += 1
            continue
        kept.append(character)
    return (''.join(kept), removed)
