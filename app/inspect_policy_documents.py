import json
from collections import defaultdict
from pathlib import Path

DATA_FILE = Path("data/vector_documents.json")


def main():
    with DATA_FILE.open("r", encoding="utf-8") as file:
        documents = json.load(file)

    policies = [
        document
        for document in documents
        if document["document_type"] == "policy"
    ]

    print("Total policy documents:", len(policies))

    # Group documents by their underlying policy text,
    # ignoring the generated section-number prefix.
    groups = defaultdict(list)

    for document in policies:
        text = document["text"]

        if ". " in text:
            policy_text = text.split(". ", 1)[1]
        else:
            policy_text = text

        groups[policy_text].append(document["id"])

    print("Unique policy passages:", len(groups))

    for number, (text, ids) in enumerate(
        groups.items(), start=1
    ):
        print("\n" + "=" * 65)
        print(f"POLICY GROUP {number}")
        print("Document IDs:", ", ".join(ids))
        print("Policy text:", text)


if __name__ == "__main__":
    main()