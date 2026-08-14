#!/usr/bin/env python3
import os
import sys
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8')
    except (AttributeError, ValueError):
        pass
sys.path.insert(0, str(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from book_to_skill.cli import main
if __name__ == '__main__':
    main()
