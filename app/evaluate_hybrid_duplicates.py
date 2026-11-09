import json
import re
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer

DATA_FILE = Path("data/duplicate_test_cases.json")

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
THRESHOLD = 0.85


def normalize(value):
    return re.sub(r"\s+", " ", value.strip().lower())


def extract_invoice(text):
    """
    Extract synthetic invoice identifiers.

    Expected format:
        HU-SYN-00016
        DE-SYN-00033
        NL-SYN-00036
    """

    match = re.search(
        r"\b(?:HU|DE|AT|NL)-SYN-\d{5}\b",
        text,
        flags=re.IGNORECASE,
    )

    return match.group(0).upper() if match else None


def extract_vendor(text):
    """
    Extract vendor information from either of the
    two receipt text templates.
    """

    if " receipt dated " in text:
        return normalize(text.split(" receipt dated ")[0])

    match = re.search(
        r"issued by (.+?)\.\s*Date:",
        text,
        flags=re.IGNORECASE,
    )

    return normalize(match.group(1)) if match else None


def evaluate():
    with DATA_FILE.open("r", encoding="utf-8") as file:
        cases = json.load(file)

    assert len(cases) == 25

    model = SentenceTransformer(MODEL_NAME)

    texts = []

    for case in cases:
        texts.extend([case["text_a"], case["text_b"]])

    embeddings = model.encode(
        texts,
        normalize_embeddings=True,
        show_progress_bar=True,
    )

    tp = fp = tn = fn = 0

    print("\n--- Hybrid duplicate detection ---")
    print("Similarity threshold:", THRESHOLD)

    for index, case in enumerate(cases):
        text_a = case["text_a"]
        text_b = case["text_b"]

        similarity = float(
            np.dot(
                embeddings[2 * index],
                embeddings[2 * index + 1],
            )
        )

        invoice_a = extract_invoice(text_a)
        invoice_b = extract_invoice(text_b)

        vendor_a = extract_vendor(text_a)
        vendor_b = extract_vendor(text_b)

        invoice_matches = (
            invoice_a is not None
            and invoice_b is not None
            and invoice_a == invoice_b
        )

        vendor_matches = (
            vendor_a is not None
            and vendor_b is not None
            and vendor_a == vendor_b
        )

        predicted = (
            similarity >= THRESHOLD
            and invoice_matches
            and vendor_matches
        )

        expected = case["expected_duplicate"]

        if predicted and expected:
            tp += 1
        elif predicted and not expected:
            fp += 1
        elif not predicted and expected:
            fn += 1
        else:
            tn += 1

        print(
            f"{case['id']}: "
            f"similarity={similarity:.4f} "
            f"invoice_match={invoice_matches} "
            f"vendor_match={vendor_matches} "
            f"predicted={predicted} "
            f"expected={expected} "
            f"{'PASS' if predicted == expected else 'FAIL'}"
        )

    precision = tp / (tp + fp) if tp + fp else 0
    recall = tp / (tp + fn) if tp + fn else 0

    f1 = (
        2 * precision * recall / (precision + recall)
        if precision + recall
        else 0
    )

    print("\n--- Confusion matrix ---")
    print("TP:", tp)
    print("FP:", fp)
    print("TN:", tn)
    print("FN:", fn)

    print("\n--- Metrics ---")
    print(f"Precision: {precision:.4f}")
    print(f"Recall:    {recall:.4f}")
    print(f"F1:        {f1:.4f}")

    assert tp + fp + tn + fn == 25

    print("\nSUCCESS: Hybrid evaluation completed.")


if __name__ == "__main__":
    evaluate()