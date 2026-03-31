#!/usr/bin/env python3
"""
build_doc_index.py - Scan all MD files, parse YAML front-matter, generate docs/INDEX.md.

Usage:
    python Scripts/build_doc_index.py

Front-matter format expected in each MD:
    ---
    title: "Document Title"
    category: architecture        # architecture|knowledge|tasks|nlp_benchmark|onboarding|paper|other
    status: current               # current|outdated|archived|completed
    updated: 2026-03-09
    tags: [tag1, tag2]
    summary: "One-line description"
    ---

Files without front-matter are listed under "No Front-matter" section.
"""

import os
import re
import sys
from datetime import datetime
from pathlib import Path
from collections import defaultdict

# Directories to scan for MD files
SCAN_DIRS = [
    'docs',
    'paper',
    'server',
    'ptycho/docs',
    'ptycho',       # for ptycho/CLAUDE.md
    'validation',
]
# Individual root-level files
ROOT_FILES = ['CLAUDE.md', 'README.md']

# Category display order and labels
CATEGORY_ORDER = [
    ('architecture', 'Architecture'),
    ('knowledge', 'Knowledge Base'),
    ('tasks', 'Tasks & Progress'),
    ('nlp_benchmark', 'NLP Benchmark'),
    ('onboarding', 'Onboarding'),
    ('paper', 'Paper'),
    ('other', 'Other'),
]


def parse_front_matter(filepath):
    """Parse YAML front-matter from a markdown file. Returns dict or None."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read(4096)  # Read only first 4KB for front-matter
    except Exception:
        return None

    # Check for --- delimited front-matter
    m = re.match(r'^---\s*\n(.*?)\n---\s*\n', content, re.DOTALL)
    if not m:
        return None

    fm = {}
    for line in m.group(1).split('\n'):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        # Simple key: value parsing (no nested YAML)
        kv = re.match(r'^(\w+)\s*:\s*(.+)$', line)
        if kv:
            key = kv.group(1).strip()
            val = kv.group(2).strip()
            # Strip quotes
            if (val.startswith('"') and val.endswith('"')) or \
               (val.startswith("'") and val.endswith("'")):
                val = val[1:-1]
            # Parse list [a, b, c]
            if val.startswith('[') and val.endswith(']'):
                val = [v.strip().strip('"').strip("'")
                       for v in val[1:-1].split(',') if v.strip()]
            fm[key] = val
    return fm if fm else None


def infer_category(filepath):
    """Infer category from file path when no front-matter."""
    fp = filepath.replace('\\', '/')
    if '/architecture/' in fp:
        return 'architecture'
    if '/knowledge/' in fp:
        return 'knowledge'
    if '/tasks/' in fp:
        return 'tasks'
    if '/nlp_benchmark/' in fp:
        return 'nlp_benchmark'
    if '/onboarding/' in fp:
        return 'onboarding'
    if '/paper/' in fp or fp.startswith('paper/'):
        return 'paper'
    return 'other'


def get_title_from_content(filepath):
    """Extract first H1/H2 heading as title."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line.startswith('# '):
                    return line.lstrip('# ').strip()
                if line.startswith('## '):
                    return line.lstrip('# ').strip()
    except Exception:
        pass
    return Path(filepath).stem


def get_file_mtime(filepath):
    """Get file modification time as YYYY-MM-DD."""
    try:
        ts = os.path.getmtime(filepath)
        return datetime.fromtimestamp(ts).strftime('%Y-%m-%d')
    except Exception:
        return '?'


def collect_md_files(base_dir):
    """Collect all MD files from scan dirs and root."""
    files = []

    for scan_dir in SCAN_DIRS:
        full = os.path.join(base_dir, scan_dir)
        if not os.path.isdir(full):
            continue
        for root, dirs, fnames in os.walk(full):
            # Skip archived, __pycache__, .venv, node_modules
            dirs[:] = [d for d in dirs if d not in
                       ('archived', '__pycache__', '.venv', 'node_modules',
                        '.git', 'reviews')]
            for fn in fnames:
                if fn.endswith('.md'):
                    fp = os.path.join(root, fn)
                    rel = os.path.relpath(fp, base_dir).replace('\\', '/')
                    files.append(rel)

    # Add archived separately (marked as archived)
    archived_dir = os.path.join(base_dir, 'docs', 'knowledge', 'archived')
    if os.path.isdir(archived_dir):
        for fn in os.listdir(archived_dir):
            if fn.endswith('.md'):
                fp = os.path.join(archived_dir, fn)
                rel = os.path.relpath(fp, base_dir).replace('\\', '/')
                files.append(rel)

    # NLP benchmark reviews
    reviews_dir = os.path.join(base_dir, 'docs', 'nlp_benchmark', 'reviews')
    if os.path.isdir(reviews_dir):
        count = sum(1 for f in os.listdir(reviews_dir) if f.endswith('.md'))
        if count > 0:
            # Add as virtual entry
            files.append('__reviews_placeholder__:' + str(count))

    # Root files
    for rf in ROOT_FILES:
        fp = os.path.join(base_dir, rf)
        if os.path.isfile(fp):
            files.append(rf)

    return sorted(set(files))


def build_index(base_dir):
    """Build the index data structure."""
    files = collect_md_files(base_dir)
    entries = []
    no_fm = []

    for rel in files:
        # Handle virtual review entry
        if rel.startswith('__reviews_placeholder__:'):
            count = rel.split(':')[1]
            entries.append({
                'path': 'docs/nlp_benchmark/reviews/',
                'title': 'NLP Benchmark Reviews (' + count + ' files)',
                'category': 'nlp_benchmark',
                'status': 'current',
                'updated': '(various)',
                'tags': ['nlp', 'benchmark', 'review'],
                'summary': 'Model-specific benchmark review reports',
                'has_fm': True,
            })
            continue

        fp = os.path.join(base_dir, rel)
        fm = parse_front_matter(fp)

        if fm:
            entries.append({
                'path': rel,
                'title': fm.get('title', get_title_from_content(fp)),
                'category': fm.get('category', infer_category(rel)),
                'status': fm.get('status', 'current'),
                'updated': fm.get('updated', get_file_mtime(fp)),
                'tags': fm.get('tags', []),
                'summary': fm.get('summary', ''),
                'has_fm': True,
            })
        else:
            cat = infer_category(rel)
            no_fm.append({
                'path': rel,
                'title': get_title_from_content(fp),
                'category': cat,
                'status': 'archived' if '/archived/' in rel else 'current',
                'updated': get_file_mtime(fp),
                'tags': [],
                'summary': '',
                'has_fm': False,
            })

    return entries, no_fm


def status_badge(status):
    """Return status indicator."""
    badges = {
        'current': 'OK',
        'outdated': 'OUTDATED',
        'archived': 'ARCHIVED',
        'completed': 'DONE',
    }
    return badges.get(status, status)


def generate_markdown(entries, no_fm, base_dir):
    """Generate INDEX.md content."""
    now = datetime.now().strftime('%Y-%m-%d %H:%M')

    lines = [
        '# Documentation Index',
        '',
        '> Auto-generated by `Scripts/build_doc_index.py` on ' + now,
        '> Run `python Scripts/build_doc_index.py` to regenerate.',
        '',
    ]

    # Summary
    total = len(entries) + len(no_fm)
    fm_count = len(entries)
    status_counts = defaultdict(int)
    for e in entries + no_fm:
        status_counts[e['status']] += 1

    lines.append('## Summary')
    lines.append('')
    lines.append('| Metric | Value |')
    lines.append('|--------|-------|')
    lines.append('| Total MD files | ' + str(total) + ' |')
    lines.append('| With front-matter | ' + str(fm_count) + ' |')
    lines.append('| Without front-matter | ' + str(len(no_fm)) + ' |')
    for st in ['current', 'completed', 'outdated', 'archived']:
        if status_counts[st] > 0:
            lines.append('| Status: ' + st + ' | ' + str(status_counts[st]) + ' |')
    lines.append('')

    # Group by category
    all_entries = entries + no_fm
    by_cat = defaultdict(list)
    for e in all_entries:
        by_cat[e['category']].append(e)

    lines.append('---')
    lines.append('')

    for cat_key, cat_label in CATEGORY_ORDER:
        cat_entries = by_cat.get(cat_key, [])
        if not cat_entries:
            continue

        lines.append('## ' + cat_label + ' (' + str(len(cat_entries)) + ')')
        lines.append('')
        lines.append('| File | Title | Status | Updated | Summary |')
        lines.append('|------|-------|--------|---------|---------|')

        for e in sorted(cat_entries, key=lambda x: x['path']):
            path = e['path']
            title = e['title'][:50]
            status = status_badge(e['status'])
            updated = str(e['updated'])
            summary = e['summary'][:80] if e['summary'] else '-'
            lines.append('| [' + os.path.basename(path) + '](' + path + ') | ' +
                          title + ' | ' + status + ' | ' + updated + ' | ' + summary + ' |')

        lines.append('')

    # Remaining categories not in CATEGORY_ORDER
    for cat_key in sorted(by_cat.keys()):
        if cat_key in [c[0] for c in CATEGORY_ORDER]:
            continue
        cat_entries = by_cat[cat_key]
        lines.append('## ' + cat_key + ' (' + str(len(cat_entries)) + ')')
        lines.append('')
        lines.append('| File | Title | Status | Updated | Summary |')
        lines.append('|------|-------|--------|---------|---------|')
        for e in sorted(cat_entries, key=lambda x: x['path']):
            path = e['path']
            title = e['title'][:50]
            status = status_badge(e['status'])
            updated = str(e['updated'])
            summary = e['summary'][:80] if e['summary'] else '-'
            lines.append('| [' + os.path.basename(path) + '](' + path + ') | ' +
                          title + ' | ' + status + ' | ' + updated + ' | ' + summary + ' |')
        lines.append('')

    # Tag index
    tag_map = defaultdict(list)
    for e in all_entries:
        tags = e.get('tags', [])
        if isinstance(tags, list):
            for t in tags:
                tag_map[t].append(e['path'])

    if tag_map:
        lines.append('---')
        lines.append('')
        lines.append('## Tag Index')
        lines.append('')
        for tag in sorted(tag_map.keys()):
            files = tag_map[tag]
            file_links = ', '.join('[' + os.path.basename(f) + '](' + f + ')' for f in sorted(files))
            lines.append('- **' + tag + '**: ' + file_links)
        lines.append('')

    return '\n'.join(lines)


def main():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    entries, no_fm = build_index(base_dir)
    content = generate_markdown(entries, no_fm, base_dir)

    out_path = os.path.join(base_dir, 'docs', 'INDEX.md')
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(content)

    print('Generated: ' + out_path)
    print('  Total: ' + str(len(entries) + len(no_fm)) + ' files')
    print('  With front-matter: ' + str(len(entries)))
    print('  Without front-matter: ' + str(len(no_fm)))


if __name__ == '__main__':
    main()
