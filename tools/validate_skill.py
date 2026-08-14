#!/usr/bin/env python3
import argparse
import re
import sys
from pathlib import Path
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8')
    except (AttributeError, ValueError):
        pass
CLAUDE_CODE_TOOLS = {'Bash', 'Read', 'Write', 'Edit', 'Glob', 'Grep', 'WebFetch', 'WebSearch', 'NotebookEdit', 'Task', 'TodoWrite'}
COPILOT_CLI_TOOLS = {'shell', 'bash', 'write'}
AMP_TOOLS = CLAUDE_CODE_TOOLS | {'shell_command'}
LENSES = {'claude': {'label': 'Claude Code', 'tools': CLAUDE_CODE_TOOLS, 'recognized_keys': {'name', 'description', 'allowed-tools', 'license'}, 'reserved_name_words': {'anthropic', 'claude'}, 'bash_tool_names': {'Bash'}, 'unknown_tool_severity': 'error'}, 'copilot': {'label': 'GitHub Copilot CLI', 'tools': COPILOT_CLI_TOOLS, 'recognized_keys': {'name', 'description', 'allowed-tools', 'license'}, 'reserved_name_words': set(), 'bash_tool_names': {'shell', 'bash'}, 'unknown_tool_severity': 'warn'}, 'amp': {'label': 'Amp', 'tools': AMP_TOOLS, 'recognized_keys': {'name', 'description', 'allowed-tools', 'license', 'compatibility', 'argument-hint'}, 'reserved_name_words': set(), 'bash_tool_names': {'shell_command', 'Bash'}, 'unknown_tool_severity': 'warn'}}

def parse_frontmatter(text):
    if not text.startswith('---'):
        return (None, None)
    end = text.find('\n---', 3)
    if end == -1:
        return (None, None)
    return (text[3:end].lstrip('\n'), text[end + 4:])

def get_scalar(fm, key):
    m = re.search(f'^{re.escape(key)}:\\s*(.*)$', fm, re.MULTILINE)
    return m.group(1).strip().strip('"').strip("'") if m else None

def get_list_items(fm, key):
    items, capturing = ([], False)
    for ln in fm.splitlines():
        if re.match(f'^{re.escape(key)}:\\s*$', ln):
            capturing = True
            continue
        if capturing:
            m = re.match('^\\s*-\\s*(.+)$', ln)
            if m:
                items.append(m.group(1).strip())
            elif re.match('^[A-Za-z][\\w-]*:', ln):
                break
    return items

def top_level_keys(fm):
    return [m.group(1) for ln in fm.splitlines() if (m := re.match('^([A-Za-z][\\w-]*):', ln))]

def tool_base(entry):
    return entry.split('(', 1)[0].strip()

def audit(path, lens='claude'):
    rules = LENSES[lens]
    label = rules['label']
    text = Path(path).read_text(encoding='utf-8')
    fm, body = parse_frontmatter(text)
    errors, warns = ([], [])
    if fm is None:
        return (['no valid YAML frontmatter (--- block)'], [])
    name = get_scalar(fm, 'name')
    if not name:
        errors.append('name: missing (required)')
    else:
        if len(name) > 64:
            errors.append(f'name: {len(name)} > 64 chars')
        if not re.fullmatch('[a-z0-9-]+', name):
            errors.append(f"name: '{name}' must be lowercase letters/digits/hyphens")
        for w in rules['reserved_name_words']:
            if w in name.lower():
                errors.append(f"name: '{name}' contains a reserved word")
                break
    desc = get_scalar(fm, 'description')
    if not desc:
        errors.append('description: missing (required)')
    elif len(desc) > 1024:
        errors.append(f'description: {len(desc)} > 1024 chars')
    tools = get_list_items(fm, 'allowed-tools')
    if not tools:
        inline = get_scalar(fm, 'allowed-tools')
        if inline:
            tools = inline.split()
    if tools:
        bases = {tool_base(t) for t in tools}
        known = {b for b in bases if b in rules['tools']}
        unknown = [t for t in tools if tool_base(t) not in rules['tools']]
        uses_bash = bool(re.search('```bash', body)) or 'python3 ' in body
        if uses_bash and (not bases & rules['bash_tool_names']):
            bash_names = ' or '.join((f"'{n}'" for n in sorted(rules['bash_tool_names'])))
            errors.append(f'allowed-tools declares a restriction but omits {bash_names}, yet the skill runs bash/python3 — under {label} those steps would be blocked')
        if not known and rules['tools']:
            if rules['unknown_tool_severity'] == 'error':
                errors.append(f'allowed-tools: no recognized {label} tool in the list')
        if unknown:
            msg = f'allowed-tools: {unknown} are not {label} built-in tool names (treated as MCP-server names by Copilot, ignored by Claude)'
            if rules['unknown_tool_severity'] == 'error':
                warns.append(msg)
            else:
                warns.append(msg)
    for k in top_level_keys(fm):
        if k not in rules['recognized_keys']:
            warns.append(f"frontmatter '{k}': not a recognized {label} key (ignored by {label})")
    n = len(text.splitlines())
    if n > 500:
        warns.append(f'body: {n} lines > 500 (soft guideline for optimal performance)')
    return (errors, warns)

def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('path', nargs='?', default='SKILL.md', help='Path to SKILL.md (default: SKILL.md)')
    parser.add_argument('--lens', choices=sorted(LENSES.keys()), default='claude', help="Which host's rules to validate against (default: claude)")
    args = parser.parse_args()
    errors, warns = audit(args.path, lens=args.lens)
    label = LENSES[args.lens]['label']
    for w in warns:
        print(f'  WARN  {w}')
    for e in errors:
        print(f'  ERROR {e}')
    if errors:
        print(f'✗ {args.path} [{label}]: {len(errors)} error(s), {len(warns)} warning(s)')
        sys.exit(1)
    print(f'✓ {args.path} [{label}]: no {label}-breaking issues ({len(warns)} warning(s))')
if __name__ == '__main__':
    main()
