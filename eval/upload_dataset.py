"""
Upload the evaluation items to LangSmith as a dataset (run once).

Run from the project folder:  python -m eval.upload_dataset
"""

import config  # noqa: F401  (loads .env and the certificate fix before connecting)
from langsmith import Client

from eval.dataset_items import ITEMS

DATASET_NAME = "downloads-organizer-files"


def main() -> None:
    client = Client()
    if client.has_dataset(dataset_name=DATASET_NAME):
        print(f"Dataset '{DATASET_NAME}' already exists - nothing uploaded.")
        print("To upload again, delete it in LangSmith first.")
        return

    dataset = client.create_dataset(
        DATASET_NAME, description="Invented Downloads files with the correct destination folder")
    client.create_examples(
        dataset_id=dataset.id,
        inputs=[{"file_name": i["file_name"], "content": i["content"]} for i in ITEMS],
        outputs=[{"folder": i["folder"]} for i in ITEMS],
    )
    print(f"Uploaded {len(ITEMS)} examples to '{DATASET_NAME}'.")


if __name__ == "__main__":
    main()
