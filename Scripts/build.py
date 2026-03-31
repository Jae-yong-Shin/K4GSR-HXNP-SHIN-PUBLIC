#!/usr/bin/env python3
"""K4GSR Virtual Beamline — Build Script

Modes:
  Patch:  python Scripts/build.py patches/fix_v4XX.js [--html base.html] [--out output.html]
  Bundle: python Scripts/build.py --bundle [--html dev.html] [--out bundle.html]
"""
import re, sys, os, subprocess, tempfile

def count_braces_outside_strings(text):
    """Count { and } outside of string literals and comments."""
    ob = cb = 0
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c == '/' and i + 1 < n:
            if text[i+1] == '/':  # line comment
                i = text.find('\n', i)
                if i == -1: break
                i += 1; continue
            elif text[i+1] == '*':  # block comment
                i = text.find('*/', i + 2)
                if i == -1: break
                i += 2; continue
        if c in ('"', "'", '`'):
            q = c; i += 1
            while i < n:
                if text[i] == '\\': i += 2; continue
                if text[i] == q: break
                i += 1
            i += 1; continue
        if c == '{': ob += 1
        elif c == '}': cb += 1
        i += 1
    return ob, cb

def verify(html, label="", vendor_included=False):
    """Brace balance, node --check, surrogate check."""
    ob, cb = count_braces_outside_strings(html)
    if ob != cb:
        if vendor_included:
            # Minified vendor code may have regex patterns with braces — warn only
            print(f"[{label}] Braces: {ob}/{cb} (diff={ob-cb}) - WARN (vendor/minified code present)")
        else:
            print(f"FAIL: Brace mismatch {{ {ob} vs }} {cb} (diff={ob-cb})")
            sys.exit(1)
    else:
        print(f"[{label}] Braces: {ob}/{cb} OK")

    # Extract all JS content for syntax check (requires node)
    scripts = re.findall(r'<script>(.*?)</script>', html, re.DOTALL)
    if scripts:
        all_js = '\n'.join(scripts)
        tmp = os.path.join(tempfile.gettempdir(), '_build_check.js')
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write(all_js)
        try:
            r = subprocess.run(['node', '--check', tmp],
                              capture_output=True, text=True)
            if r.returncode != 0:
                print(f"FAIL: node --check\n{r.stderr}")
                sys.exit(1)
            print(f"[{label}] node --check: PASS")
        except FileNotFoundError:
            print(f"[{label}] node --check: SKIPPED (node not installed)")

    for i, ch in enumerate(html):
        if 0xD800 <= ord(ch) <= 0xDFFF:
            print(f"WARN: Surrogate at pos {i}")
            break


def esm_bundle_mode(html_file, out_file):
    """ESM mode: use esbuild to bundle js/main.js into a single IIFE script.

    Produces the same output format as bundle_mode (single inline <script>),
    but uses esbuild for proper module resolution and scope isolation.
    Requires: npm install esbuild --save-dev
    """
    with open(html_file, 'r', encoding='utf-8') as f:
        html = f.read()

    html_dir = os.path.dirname(os.path.abspath(html_file))
    main_js = os.path.join(html_dir, 'js', 'main.js')
    if not os.path.isfile(main_js):
        print("ERROR: js/main.js not found. Create it first.")
        sys.exit(1)

    # Run esbuild
    dist_dir = os.path.join(html_dir, 'dist')
    os.makedirs(dist_dir, exist_ok=True)
    bundle_path = os.path.join(dist_dir, 'bundle.js')
    npx = 'npx.cmd' if os.name == 'nt' else 'npx'
    esbuild_cmd = [npx, 'esbuild', main_js, '--bundle', '--format=iife',
                   f'--outfile={bundle_path}', '--log-level=warning']
    print(f"[esm] Running: {' '.join(esbuild_cmd)}")
    r = subprocess.run(esbuild_cmd, capture_output=True, text=True, cwd=html_dir)
    if r.returncode != 0:
        print(f"FAIL: esbuild\n{r.stderr}")
        sys.exit(1)
    print(f"[esm] esbuild: OK ({os.path.getsize(bundle_path)} bytes)")

    with open(bundle_path, 'r', encoding='utf-8') as f:
        bundle_js = f.read()

    # Remove all <script src="js/..."> and <script src="vendor/..."> tags
    pattern_js = re.compile(r'<script\s+src="(js|vendor)/[^"]+\.js"\s*></script>\s*\n?')
    html_no_scripts = pattern_js.sub('', html)

    # Read vendor files (uplot etc.) — inline them before the bundle
    vendor_pattern = re.compile(r'<script\s+src="(vendor/[^"]+\.js)"\s*></script>')
    vendor_js = []
    for m in vendor_pattern.finditer(html):
        vpath = os.path.join(html_dir, m.group(1))
        if os.path.isfile(vpath):
            with open(vpath, 'r', encoding='utf-8') as f:
                vendor_js.append(f.read())

    # Insert vendor + esbuild bundle before </body>
    body_end = html_no_scripts.rfind('</body>')
    if body_end == -1:
        print("ERROR: </body> not found")
        sys.exit(1)

    inject = ''
    if vendor_js:
        inject += '<script>\n' + '\n'.join(vendor_js) + '\n</script>\n'
    inject += '<script>\n' + bundle_js + '\n</script>\n'

    final_html = html_no_scripts[:body_end] + inject + html_no_scripts[body_end:]

    # Verify
    verify(final_html, "esm", vendor_included=bool(vendor_js))

    with open(out_file, 'w', encoding='utf-8') as f:
        f.write(final_html)
    print(f"ESM Bundle: js/main.js -> esbuild -> {out_file} ({len(final_html.splitlines())} lines)")


def bundle_mode(html_file, out_file):
    """Replace all <script src="js/..."> tags with a single inline <script> block.

    Uses ONE <script> block (not multiple) to match the original's execution model:
    - 'use strict' directives behave identically (not as first statement)
    - All code shares the same script scope for let/const
    """
    with open(html_file, 'r', encoding='utf-8') as f:
        html = f.read()

    html_dir = os.path.dirname(os.path.abspath(html_file))

    # Collect all script src tags and their JS content in order
    pattern = re.compile(r'<script\s+src="([^"]+\.js)"\s*></script>')
    js_parts = []
    for m in pattern.finditer(html):
        src_path = m.group(1)
        full_path = os.path.join(html_dir, src_path)
        if not os.path.isfile(full_path):
            print(f"ERROR: File not found: {full_path}")
            sys.exit(1)
        with open(full_path, 'r', encoding='utf-8') as f:
            js_content = f.read()
        js_parts.append(f'// === {src_path} ===\n{js_content}')

    if not js_parts:
        print("ERROR: No <script src> tags found")
        sys.exit(1)

    # Replace all script src tags with a single inline script
    combined_js = '\n'.join(js_parts)
    # Remove all script src tags
    html_no_scripts = pattern.sub('', html)
    # Insert single script block before </body>
    body_end = html_no_scripts.rfind('</body>')
    if body_end == -1:
        print("ERROR: </body> not found")
        sys.exit(1)
    html = html_no_scripts[:body_end] + f'<script>\n{combined_js}\n</script>\n' + html_no_scripts[body_end:]

    has_vendor = any('vendor/' in part for part in js_parts)
    verify(html, "bundle", vendor_included=has_vendor)
    with open(out_file, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"Bundle: {len(js_parts)} JS files -> single <script> -> {out_file} ({len(html.splitlines())} lines)")


def patch_mode(patch_file, html_file, out_file):
    """Insert patch JS before </script> (original behavior)."""
    with open(html_file, 'r', encoding='utf-8') as f:
        html = f.read()
    with open(patch_file, 'r', encoding='utf-8') as f:
        patch = f.read()

    ver = re.search(r'v(\d+\w*)', patch_file)
    ver_str = ver.group(0) if ver else 'patch'

    marker = '</script>'
    idx = html.rfind(marker)
    if idx == -1:
        print("ERROR: </script> not found")
        sys.exit(1)
    html = html[:idx] + f'\n// ===== {ver_str} =====\n' + patch + '\n' + html[idx:]

    verify(html, "patch")
    with open(out_file, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"Output: {out_file} ({len(html.splitlines())} lines)")


def main():
    is_bundle = '--bundle' in sys.argv
    is_esm = '--esm' in sys.argv

    # Parse --html and --out
    html_file = None
    out_file = None
    for i, arg in enumerate(sys.argv):
        if arg == '--html' and i + 1 < len(sys.argv):
            html_file = sys.argv[i + 1]
        if arg == '--out' and i + 1 < len(sys.argv):
            out_file = sys.argv[i + 1]

    if is_esm:
        if not html_file:
            html_file = 'virtual_beamline_nanoprobe_V4_36.html'
        if not out_file:
            base, ext = os.path.splitext(html_file)
            out_file = base + '_bundle' + ext
        esm_bundle_mode(html_file, out_file)
    elif is_bundle:
        if not html_file:
            html_file = 'K4GSR-Beamline/virtual_beamline_nanoprobe_V4_36.html'
        if not out_file:
            base, ext = os.path.splitext(html_file)
            out_file = base + '_bundle' + ext
        bundle_mode(html_file, out_file)
    else:
        # Patch mode — needs a patch file as first non-flag argument
        patch_file = None
        for arg in sys.argv[1:]:
            if not arg.startswith('--') and patch_file is None:
                patch_file = arg
        if not patch_file:
            print("Usage:")
            print("  Patch:  python Scripts/build.py patches/fix.js [--html base.html] [--out out.html]")
            print("  Bundle: python Scripts/build.py --bundle [--html dev.html] [--out bundle.html]")
            sys.exit(1)
        if not html_file:
            html_file = 'virtual_beamline_nanoprobe.html'
        if not out_file:
            out_file = html_file
        patch_mode(patch_file, html_file, out_file)


if __name__ == '__main__':
    main()
