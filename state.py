"""
Data shapes used by the agent.

1. Pydantic models: the fixed structure the model must answer with (structured output).
2. GraphState: everything the LangGraph graph remembers between nodes.
"""

from typing import TypedDict

from pydantic import BaseModel, Field


# ---------- what the model returns ----------

class FileClassification(BaseModel):
    """The model's decision for one file."""
    file_name: str = Field(description="The exact file name, copied from the input")
    folder: str = Field(description="Destination folder name: an existing folder, or a short new name")
    is_new_folder: bool = Field(description="True only if the folder is not in the existing folders list")
    confidence: float = Field(description="How sure you are, from 0.0 to 1.0")
    unclear_name: bool = Field(description="True if the name alone is not enough to know what the file is about")
    reason: str = Field(description="One short sentence in Hebrew explaining the choice")
    suggested_name: str = Field(description="Only when you were given the file content: a short descriptive "
                                            "file name WITHOUT extension, in the language of the content. "
                                            "Otherwise an empty string")


class ClassificationBatch(BaseModel):
    """The model's answer for a group of files: one item per file."""
    classifications: list[FileClassification]


# ---------- what the graph remembers ----------

class GraphState(TypedDict, total=False):
    source_dir: str
    dest_root: str
    folder_list: list[dict]         # the user's folder list: {name, description} (see folders.py)
    existing_folders: list[str]     # names from folder_list + folders already on disk
    folder_descriptions: dict[str, str]  # name -> description, for the prompt
    files: list[dict]               # files to organize (from file_tools.scan_folder)
    skipped: list[dict]             # temporary / system files that were not touched
    deleted_duplicates: list[dict]  # identical copies sent to the Recycle Bin
    classifications: dict[str, dict]  # file name -> FileClassification as dict + "used_content"
    content_requests: list[str]     # file names whose content should be read
    content_texts: dict[str, str]   # name -> extracted text, cleared right after classification
    excluded: list[str]             # files the user removed from the plan (stay in Downloads)
    plan: list[dict]                # actions shown for approval
    review_result: dict             # the user's answer from the interrupt
    executed: list[dict]            # what actually happened
    report: dict                    # final summary
