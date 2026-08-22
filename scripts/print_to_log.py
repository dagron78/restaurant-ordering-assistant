"""AST-based print()->logger rewrite (char-offset splicing, nested safe)."""
import ast
import io
import pathlib

LEVEL_HINTS = ('error', 'fail', '✗', 'skipping', 'dropping',
               'not configured', 'no valid session', 'abort')


def _char_offset(src_lines, lineno, col):
    return sum(len(ln) for ln in src_lines[:lineno - 1]) + col


def transform(path: pathlib.Path) -> int:
    src = io.open(path, encoding='utf-8').read()
    tree = ast.parse(src)

    sites = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name) and n.func.id == 'print']
    if not sites:
        return 0

    has_logging_import = any(
        isinstance(n, ast.Import) and any(a.name == 'logging' for a in n.names)
        for n in tree.body)
    alias = 'logger' if 'getLogger(' in src else 'log'

    src_lines = src.splitlines(keepends=True)

    # build (char_start, char_end, level, inner) tuples
    edits = []
    for node in sites:
        seg = ast.get_source_segment(src, node)
        inner = seg[len('print('):-1]
        level = ('warning'
                 if any(h in inner.lower() for h in LEVEL_HINTS) else 'info')
        cs = _char_offset(src_lines, node.lineno, node.col_offset)
        ce = _char_offset(src_lines, node.end_lineno, node.end_col_offset)
        edits.append((cs, ce, f"{alias}.{level}({inner})"))
    edits.sort(reverse=True)

    out = src
    for cs, ce, repl in edits:
        out = out[:cs] + repl + out[ce:]

    tree2 = ast.parse(out)                      # must still parse
    anchor = max((n.end_lineno for n in tree2.body
                  if isinstance(n, (ast.Import, ast.ImportFrom))), default=0)
    out_lines = out.splitlines(keepends=True)
    inject = ""
    if not has_logging_import:
        inject += "import logging\n"
    inject += f"\n{alias} = logging.getLogger(__name__)\n"
    out_lines.insert(anchor, inject)
    out = ''.join(out_lines[:anchor]) + inject + ''.join(out_lines[anchor:])

    ast.parse(out)                              # final sanity
    io.open(path, 'w', encoding='utf-8').write(out)
    return len(sites)


if __name__ == '__main__':
    total = 0
    targets = [x for x in list(pathlib.Path('core').glob('*.py'))
               + list(pathlib.Path('workers').glob('*.py'))
               if x.name != '__init__.py']
    for p in targets:
        n = transform(p)
        total += n
        print(f"{p}: {n} sites")
    print("TOTAL", total)
