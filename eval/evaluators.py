"""
Scoring functions for the LangSmith experiments.
Each gets the agent's answer (outputs) and the correct answer (reference_outputs).
"""


def correct_folder(outputs: dict, reference_outputs: dict) -> dict:
    """1 if the chosen folder is the correct one, else 0."""
    return {"key": "correct_folder",
            "score": int(outputs.get("folder") == reference_outputs["folder"])}


def no_unneeded_new_folder(outputs: dict, reference_outputs: dict) -> dict:
    """
    0 if the agent suggested a new folder although the correct folder already exists, else 1.
    (Every correct folder in the dataset is an existing base folder.)
    """
    return {"key": "no_unneeded_new_folder",
            "score": int(not outputs.get("is_new_folder", False))}
