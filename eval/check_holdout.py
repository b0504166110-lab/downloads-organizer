"""
Fairness check: run the "before" and "after" prompts on a SEPARATE set of files -
the fake files of the test folder (test_data/make_test_folder.py), which were not
part of the LangSmith dataset and were not used to write the improvement.

No LangSmith experiment, nothing is moved. Prints both scores and the mistakes.
Run from the project folder:
    python -m eval.check_holdout                 # before and after
    python -m eval.check_holdout --only after    # just one of them
    python -m eval.check_holdout --explain       # also show what the model answered for each mistake
    python -m eval.check_holdout --file "רשימת קניות.txt" --explain   # one file only (part of the name is enough)
"""

import argparse
import hashlib
import sys
import tempfile
from pathlib import Path

import config
import file_tools
import nodes
import prompts

sys.path.insert(0, str(config.PROJECT_DIR / "test_data"))
from make_test_folder import build_files  # noqa: E402


def load_items() -> list[dict]:
    """Test-folder files with their correct folder; content is extracted like the agent does."""
    items = []
    with tempfile.TemporaryDirectory() as tmp:
        for name, data, expected in build_files():
            if expected == "SKIP":
                continue
            path = Path(tmp) / name
            path.write_bytes(data)
            content = file_tools.extract_text(path, config.CONTENT_MAX_CHARS) if file_tools.can_read_content(path.suffix) else None
            items.append({"file_name": name, "content": content, "folder": expected})
    return items


def prompt_fingerprint() -> str:
    """Short fingerprint of the exact system prompt - same fingerprint = same prompt."""
    return hashlib.sha256(prompts.system_prompt().encode("utf-8")).hexdigest()[:10]


def score(items: list[dict], improved: bool, keep_all: bool = False) -> tuple[int, list]:
    """Returns (correct count, rows). Rows are the mistakes - or every file when keep_all is True."""
    prompts.USE_IMPROVEMENT = improved  # switch the prompt version for this run only
    correct, rows = 0, []
    for item in items:
        result = nodes.classify_one(item["file_name"], item["content"], config.BASE_FOLDERS)
        ok = result["folder"] == item["folder"]
        correct += ok
        if keep_all or not ok:
            rows.append((item["file_name"], result["folder"], item["folder"], result["trace"]))
    return correct, rows


def _stage(c: dict | None) -> str:
    if not c:
        return "no answer"
    return f"{c['folder']} | confidence={c['confidence']} | unclear_name={c['unclear_name']} | {c['reason']}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", choices=["before", "after"], help="run just one version")
    parser.add_argument("--explain", action="store_true", help="show the model's answers for each mistake")
    parser.add_argument("--file", help="check only files whose name contains this text")
    args = parser.parse_args()
    items = load_items()
    if args.file:
        items = [i for i in items if args.file in i["file_name"]]
        if not items:
            raise SystemExit(f"No test file contains: {args.file}")
    versions = [("before", False), ("after", True)]
    for label, improved in [v for v in versions if args.only in (None, v[0])]:
        correct, mistakes = score(items, improved, keep_all=bool(args.file))  # --file: show every result
        print(f"\n{label:6} {correct}/{len(items)} = {correct / len(items):.0%}   (prompt {prompt_fingerprint()})")
        for name, got, want, trace in mistakes:
            print(f"   {name} -> {got} | {want}" + ("   ✓" if got == want else "   ✗"))
            if args.explain:
                print(f"      by name:    {_stage(trace['by_name'])}")
                print(f"      content read: {trace['content_read']}")
                if trace["content_read"]:
                    print(f"      by content: {_stage(trace['by_content'])}")


if __name__ == "__main__":
    main()
