"""
Run an experiment on the LangSmith dataset: only the classification step
(no files are moved, no approval) - exactly the same code the graph uses.

Run from the project folder:
    python -m eval.run_experiment before        # USE_IMPROVEMENT=false in .env
    python -m eval.run_experiment after         # USE_IMPROVEMENT=true  in .env
"""

import argparse

import config
from langsmith import evaluate

from eval.evaluators import correct_folder, no_unneeded_new_folder
from eval.upload_dataset import DATASET_NAME
from nodes import classify_one


def target(inputs: dict) -> dict:
    """What is being tested: one file in -> the agent's decision out."""
    return classify_one(inputs["file_name"], inputs.get("content"), config.BASE_FOLDERS)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("label", choices=["before", "after"])
    args = parser.parse_args()

    # Guard against a mislabeled experiment
    if (args.label == "after") != config.USE_IMPROVEMENT:
        raise SystemExit(f"'{args.label}' needs USE_IMPROVEMENT={'true' if args.label == 'after' else 'false'} in .env")

    results = evaluate(
        target,
        data=DATASET_NAME,
        evaluators=[correct_folder, no_unneeded_new_folder],
        experiment_prefix=args.label,
        metadata={"label": args.label, "model": config.MODEL_NAME, "use_improvement": config.USE_IMPROVEMENT},
        max_concurrency=4,
    )

    # Short summary in the terminal (the full view is in LangSmith)
    scores = {"correct_folder": [], "no_unneeded_new_folder": []}
    mistakes = []
    for row in results:
        for ev in row["evaluation_results"]["results"]:
            scores[ev.key].append(ev.score)
        if row["evaluation_results"]["results"][0].score == 0:
            mistakes.append((row["example"].inputs["file_name"],
                             row["run"].outputs.get("folder"), row["example"].outputs["folder"]))
    for key, values in scores.items():
        if values:
            print(f"{key:24} {sum(values)}/{len(values)} = {sum(values) / len(values):.0%}")
    if mistakes:
        print("\nMistakes (file -> chosen | correct):")
        for name, got, want in mistakes:
            print(f"  {name} -> {got} | {want}")


if __name__ == "__main__":
    main()
