#!/usr/bin/env python3
"""
rtl_parser.py — Extract DUT top-module port list from a Verilog/SystemVerilog file.

Emits JSON to stdout:
    [{"name": <str>, "dir": "input|output|inout", "width_expr": <str>}, ...]

Handles:
  - Verilog-2001 ANSI-style port declarations (dir + optional width + name)
  - Multi-line port lists
  - Line and block comments
  - Optional reg/wire/logic/signed/unsigned keywords
  - Optional parameter block #( ... )
  - Optional packed dimension (e.g. [WIDTH-1:0], [7:0], [OC_NUM*8-1:0])

Does NOT handle:
  - Verilog-95 style (separate port list + separate declarations)
  - Preprocessor macros that expand to port declarations
  - Nested / multiple modules per file (only the module matching --top is parsed)

Stdlib only. No third-party deps.
"""

import argparse
import json
import re
import sys


def strip_comments(text: str) -> str:
    """Strip /* ... */ block and // line comments."""
    text = re.sub(r'/\*.*?\*/', ' ', text, flags=re.DOTALL)
    text = re.sub(r'//[^\n]*', '', text)
    return text


def find_module_header(text: str, top_name: str):
    """Return the port-list body (contents between outer parens after params), or None."""
    m = re.search(rf'\bmodule\s+{re.escape(top_name)}\b', text)
    if not m:
        return None

    i = m.end()
    n = len(text)

    # Skip whitespace
    while i < n and text[i].isspace():
        i += 1

    # Optional parameter block #( ... )
    if i < n and text[i] == '#':
        i += 1
        while i < n and text[i].isspace():
            i += 1
        if i < n and text[i] == '(':
            depth = 1
            i += 1
            while i < n and depth > 0:
                if text[i] == '(':
                    depth += 1
                elif text[i] == ')':
                    depth -= 1
                i += 1

    # Skip whitespace to reach port list
    while i < n and text[i].isspace():
        i += 1

    if i >= n or text[i] != '(':
        return None

    # Extract balanced port-list body
    depth = 1
    start = i + 1
    i += 1
    while i < n and depth > 0:
        if text[i] == '(':
            depth += 1
        elif text[i] == ')':
            depth -= 1
            if depth == 0:
                return text[start:i]
        i += 1
    return None


def split_ports(body: str):
    """Split port-list body on top-level commas (not inside [], (), {})."""
    ports = []
    depth = 0
    buf = []
    for ch in body:
        if ch in '[({':
            depth += 1
            buf.append(ch)
        elif ch in '])}':
            depth -= 1
            buf.append(ch)
        elif ch == ',' and depth == 0:
            token = ''.join(buf).strip()
            if token:
                ports.append(token)
            buf = []
        else:
            buf.append(ch)
    tail = ''.join(buf).strip()
    if tail:
        ports.append(tail)
    return ports


PORT_DECL_RE = re.compile(
    r'''^
    (?P<dir>input|output|inout)\b            # direction
    (?:\s+(?:reg|wire|logic|signed|unsigned))*
    (?P<width>\s*\[[^\]]+\])?                 # optional packed dim [W-1:0]
    \s+
    (?P<name>[A-Za-z_][A-Za-z0-9_]*)          # port name
    \s*
    (?:\[[^\]]+\])?                           # optional unpacked dim
    \s*
    $
    ''',
    re.VERBOSE
)


def parse_ports(port_tokens):
    """Turn raw port declaration strings into dicts of {name, dir, width_expr}."""
    ports = []
    last_dir = None
    last_width = None

    for tok in port_tokens:
        norm = ' '.join(tok.split())  # collapse whitespace
        m = PORT_DECL_RE.match(norm)
        if m:
            direction = m.group('dir')
            width = m.group('width')
            name = m.group('name')
            width_expr = width.strip()[1:-1].strip() if width else '1'
            ports.append({
                "name": name,
                "dir": direction,
                "width_expr": width_expr,
            })
            last_dir = direction
            last_width = width_expr
            continue

        # Inheritance case: bare name reuses previous dir/width
        name_m = re.match(r'^([A-Za-z_][A-Za-z0-9_]*)$', norm)
        if name_m and last_dir:
            ports.append({
                "name": name_m.group(1),
                "dir": last_dir,
                "width_expr": last_width or '1',
            })
            continue

        # Could not parse — surface as an error entry (do not silently drop)
        ports.append({
            "name": None,
            "dir": None,
            "width_expr": None,
            "raw": tok,
            "error": "unparseable port declaration",
        })
    return ports


def main():
    ap = argparse.ArgumentParser(description="Extract top-module port list from Verilog/SV.")
    ap.add_argument('rtl_file', help="Path to the RTL file containing the DUT top module")
    ap.add_argument('--top', required=True, help="DUT top module name")
    args = ap.parse_args()

    try:
        with open(args.rtl_file, 'r') as f:
            text = f.read()
    except OSError as e:
        print(f"ERROR: cannot read {args.rtl_file}: {e}", file=sys.stderr)
        sys.exit(2)

    stripped = strip_comments(text)
    body = find_module_header(stripped, args.top)
    if body is None:
        print(f"ERROR: could not locate module '{args.top}' or its port list in {args.rtl_file}",
              file=sys.stderr)
        sys.exit(1)

    tokens = split_ports(body)
    ports = parse_ports(tokens)

    errors = [p for p in ports if p.get('error')]
    if errors:
        print(f"WARN: {len(errors)} port(s) could not be parsed:", file=sys.stderr)
        for e in errors:
            print(f"  {e['raw']!r}", file=sys.stderr)

    json.dump(ports, sys.stdout, indent=2)
    sys.stdout.write('\n')


if __name__ == '__main__':
    main()
