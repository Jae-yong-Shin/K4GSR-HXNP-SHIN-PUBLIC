"""Generate a comprehensive review table from benchmark results.

Merges test prompts (from test_nlp_benchmark.py) with model responses (from JSON)
to produce a markdown table for human review.

Usage:
    python docs/nlp_benchmark/generate_review_table.py <results_json>
"""
import json
import re
import sys
import os

def extract_prompts_from_test_file(test_file):
    """Extract test ID -> input prompt mapping from test_nlp_benchmark.py."""
    with open(test_file, "r", encoding="utf-8") as f:
        content = f.read()

    prompts = {}
    # Find all "id": "xxx" ... "cat": "yyy" ... "input": "zzz" triplets
    # Use finditer on "id" lines, then search forward for cat and input
    for m in re.finditer(r'"id":\s*"([^"]+)"', content):
        test_id = m.group(1)
        # Search in the next 500 chars for cat and input
        chunk = content[m.start():m.start() + 1000]
        cat_match = re.search(r'"cat":\s*"([^"]+)"', chunk)
        input_match = re.search(r'"input":\s*"((?:[^"\\]|\\.)*)"', chunk)
        if input_match:
            prompt = input_match.group(1)
            prompt = prompt.replace('\\"', '"').replace('\\n', '\n')
            cat = cat_match.group(1) if cat_match else "unknown"
            prompts[test_id] = {"input": prompt, "cat": cat}
    return prompts


def format_actions(actions):
    """Format actions list into a compact string."""
    if not actions:
        return "(empty)"
    parts = []
    for a in actions:
        fn = a.get("fn", "?")
        args = a.get("args", [])
        if args:
            args_str = ", ".join(str(x) for x in args)
            parts.append(f"{fn}({args_str})")
        else:
            parts.append(f"{fn}()")
    return " -> ".join(parts)


def truncate(text, max_len=200):
    """Truncate text to max_len chars."""
    if not text:
        return ""
    text = text.replace("\n", " ").strip()
    if len(text) > max_len:
        return text[:max_len] + "..."
    return text


def main():
    if len(sys.argv) < 2:
        print("Usage: python generate_review_table.py <results_json>")
        sys.exit(1)

    results_json = sys.argv[1]
    # Try multiple locations for test_nlp_benchmark.py
    candidates = [
        os.path.join(os.path.dirname(__file__), "..", "..", "server", "test_nlp_benchmark.py"),
        os.path.join(os.path.dirname(os.path.dirname(results_json)), "test_nlp_benchmark.py"),
        os.path.join(os.path.dirname(__file__), "..", "test_nlp_benchmark.py"),
    ]
    test_file = None
    for c in candidates:
        if os.path.exists(c):
            test_file = c
            break
    if test_file is None:
        print("ERROR: test_nlp_benchmark.py not found")
        sys.exit(1)

    # Load results
    with open(results_json, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Extract prompts
    prompts = extract_prompts_from_test_file(test_file)

    # Build table
    details = data.get("details", [])

    lines = []
    lines.append(f"# NLP Benchmark Full Response Review")
    lines.append(f"")
    lines.append(f"**Model**: {data.get('model', '?')}")
    lines.append(f"**Engine**: {data.get('engine', '?')}")
    lines.append(f"**Date**: {data.get('timestamp', '?')[:10]}")
    lines.append(f"**Total**: {data.get('total', '?')} | **Pass**: {data.get('pass', '?')} | **Fail**: {data.get('fail', '?')} | **Rate**: {data.get('pass_rate', '?')}%")
    lines.append(f"")
    lines.append(f"## Review Guide")
    lines.append(f"")
    lines.append(f"For each test, review whether the model's actions are **truly appropriate** for the user's prompt.")
    lines.append(f"Mark items that need correction with suggested fixes.")
    lines.append(f"")

    # Group by category
    cat_order = []
    cat_tests = {}
    for d in details:
        tid = d["id"]
        p = prompts.get(tid, {})
        cat = p.get("cat", "unknown")
        if cat not in cat_tests:
            cat_order.append(cat)
            cat_tests[cat] = []
        cat_tests[cat].append((tid, d, p))

    for cat in cat_order:
        tests = cat_tests[cat]
        lines.append(f"---")
        lines.append(f"")
        lines.append(f"## {cat} ({len(tests)} tests)")
        lines.append(f"")

        for tid, d, p in tests:
            passed = d.get("passed", False)
            status = "PASS" if passed else "**FAIL**"
            resp = d.get("response", {}) or {}
            actions = resp.get("actions", [])
            explanation = resp.get("explanation", "")
            confirm = resp.get("confirmation_required", None)
            elapsed = d.get("elapsed_s", 0)
            errors = d.get("errors", [])
            prompt_text = p.get("input", "(prompt not found)")

            lines.append(f"### {tid} [{status}] ({elapsed:.1f}s)")
            lines.append(f"")
            lines.append(f"**Prompt**: {prompt_text}")
            lines.append(f"")
            lines.append(f"**Actions**: {format_actions(actions)}")
            lines.append(f"")
            if confirm is not None:
                lines.append(f"**Confirmation**: {confirm}")
                lines.append(f"")
            lines.append(f"**Explanation**: {truncate(explanation, 300)}")
            lines.append(f"")
            if errors:
                lines.append(f"**Errors**: {'; '.join(errors)}")
                lines.append(f"")
            lines.append(f"**Verdict**: [ ] OK / [ ] Wrong action / [ ] Missing action / [ ] Unnecessary action")
            lines.append(f"")

    # Write output -- place in reviews/ sibling directory if it exists
    reviews_dir = os.path.join(os.path.dirname(results_json), "..", "reviews")
    if os.path.isdir(reviews_dir):
        out_path = os.path.join(reviews_dir, os.path.basename(results_json).replace(".json", "_REVIEW.md"))
    else:
        out_path = results_json.replace(".json", "_REVIEW.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"Review table written to: {out_path}")
    print(f"Total tests: {len(details)}")


if __name__ == "__main__":
    main()
