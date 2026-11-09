
from sentence_transformers import SentenceTransformer
import numpy as np


MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


DOCUMENTS = [
    {
        "id": "receipt_001",
        "document_type": "receipt",
        "text": "Office Supplies Ltd invoice 2026-001. Purchase of printer paper and pens. Total 125.50 EUR.",
    },
    {
        "id": "receipt_002",
        "document_type": "receipt",
        "text": "Office Supplies Limited invoice 2026-001. Printer paper and pens purchased. Amount paid 125.50 EUR.",
    },
    {
        "id": "receipt_003",
        "document_type": "receipt",
        "text": "City Taxi receipt 2026-002. Taxi ride to client meeting. Total 38.00 EUR.",
    },
    {
        "id": "receipt_004",
        "document_type": "receipt",
        "text": "Tech Store invoice 2026-003. Wireless keyboard and mouse. Total 89.99 EUR.",
    },
    {
        "id": "receipt_005",
        "document_type": "receipt",
        "text": "Hotel Central invoice 2026-004. One night accommodation during business trip. Total 140 EUR.",
    },
    {
        "id": "policy_001",
        "document_type": "policy",
        "text": "Employees may claim business travel expenses when travel is necessary for approved company activities.",
    },
    {
        "id": "policy_002",
        "document_type": "policy",
        "text": "Hotel accommodation must be reasonable and should not exceed the approved nightly allowance.",
    },
    {
        "id": "policy_003",
        "document_type": "policy",
        "text": "Taxi expenses are reimbursable when public transport is unavailable or impractical for business travel.",
    },
    {
        "id": "policy_004",
        "document_type": "policy",
        "text": "Computer equipment and accessories require manager approval before purchase.",
    },
    {
        "id": "policy_005",
        "document_type": "policy",
        "text": "Receipts must include the vendor name, VAT number, transaction date, and total amount.",
    },
]


def generate_embeddings():
    model = SentenceTransformer(MODEL_NAME)

    texts = [document["text"] for document in DOCUMENTS]

    embeddings = model.encode(
        texts,
        normalize_embeddings=True,
    )

    embeddings = np.asarray(embeddings, dtype=np.float32)

    print(f"Documents: {len(DOCUMENTS)}")
    print(f"Embedding dimensions: {embeddings.shape[1]}")
    print(f"Normalized: {np.allclose(np.linalg.norm(embeddings, axis=1), 1.0)}")

    return embeddings


if __name__ == "__main__":
    generate_embeddings()
