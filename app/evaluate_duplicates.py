import json
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer

DATA_FILE = Path("data/duplicate_test_cases.json")
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

# Initial threshold chosen before examining evaluation results.
THRESHOLD = 0.85


def main():
    with DATA_FILE.open("r", encoding="utf-8") as file:
        cases = json.load(file)

    assert len(cases) == 25

    model = SentenceTransformer(MODEL_NAME)

    # Encode all texts together for efficiency.
    texts = []

    for case in cases:
        texts.append(case["text_a"])
        texts.append(case["text_b"])

    embeddings = model.encode(
        texts,
        normalize_embeddings=True,
        show_progress_bar=True,
    )

    tp = 0
    fp = 0
    tn = 0
    fn = 0

    print("\n--- Duplicate detection results ---")
    print("Threshold:", THRESHOLD)

    for index, case in enumerate(cases):
        embedding_a = embeddings[2 * index]
        embedding_b = embeddings[2 * index + 1]

        # Dot product equals cosine similarity because
        # both embeddings are normalized.
        similarity = float(
            np.dot(embedding_a, embedding_b)
        )

        predicted_duplicate = similarity >= THRESHOLD
        expected_duplicate = case["expected_duplicate"]

        if predicted_duplicate and expected_duplicate:
            tp += 1

        elif predicted_duplicate and not expected_duplicate:
            fp += 1

        elif not predicted_duplicate and expected_duplicate:
            fn += 1

        else:
            tn += 1

        print(
            f"{case['id']}: "
            f"similarity={similarity:.4f} "
            f"expected={expected_duplicate} "
            f"predicted={predicted_duplicate} "
            f"{'PASS' if predicted_duplicate == expected_duplicate else 'FAIL'}"
        )

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0

    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall)
        else 0.0
    )

    accuracy = (tp + tn) / len(cases)

    print("\n--- Confusion matrix ---")
    print("True positives:", tp)
    print("False positives:", fp)
    print("True negatives:", tn)
    print("False negatives:", fn)

    print("\n--- Evaluation metrics ---")
    print(f"Precision: {precision:.4f}")
    print(f"Recall:    {recall:.4f}")
    print(f"F1 score:  {f1:.4f}")
    print(f"Accuracy:  {accuracy:.4f}")

    assert tp + fp + tn + fn == len(cases)

    print("\nSUCCESS: Duplicate detection evaluation completed.")


if __name__ == "__main__":
    main()