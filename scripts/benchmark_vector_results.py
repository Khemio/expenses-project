"""Read-only, labelled evaluation for the final 455-document vector dataset.

From the repository root (development databases, NOT the integration-test runner):
    python -m scripts.benchmark_vector_results

If the PostgreSQL HNSW index has not been installed, explicitly opt in:
    python -m scripts.benchmark_vector_results --install-pg-hnsw

The default path does not change any records, indexes or search configuration.
Only --install-pg-hnsw changes the PostgreSQL database schema (an index).
Never silently create fake embeddings, evaluation labels or missing source data.
"""

import argparse
import json
from collections import Counter
import statistics
import time
import uuid
from pathlib import Path

import numpy as np
from qdrant_client import models
from sentence_transformers import SentenceTransformer

from app.database.benchmark_queries import BENCHMARK_QUERIES
from app.database.postgres import get_connection
from app.database.qdrant import get_qdrant_client
from app.database.vector_store import COLLECTION_NAME, MODEL_NAME


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
K = 10
EXPECTED_DOCUMENTS = 455
EXPECTED_RARE = 23


def read_labels(filename):
    return json.loads((DATA / filename).read_text(encoding="utf-8"))


def qdrant_filter(key, value):
    return models.Filter(must=[
        models.FieldCondition(
            key=key, match=models.MatchValue(value=value)
        )
    ])


def check_dataset(pg, qdrant):
    pg_rows = pg.execute(
        "SELECT id, document_type, filter_group FROM vector_documents"
    ).fetchall()
    if len(pg_rows) != EXPECTED_DOCUMENTS:
        raise RuntimeError(
            f"PostgreSQL has {len(pg_rows)} vectors, expected "
            f"{EXPECTED_DOCUMENTS}; seed and index the development dataset first"
        )

    pg_data = {row[0]: (row[1], row[2]) for row in pg_rows}
    pg_rare = sum(row[2] == "rare" for row in pg_rows)
    if pg_rare != EXPECTED_RARE:
        raise RuntimeError(
            f"PostgreSQL has {pg_rare} rare vectors, expected "
            f"{EXPECTED_RARE}. Check app.database.prepare_rare_filter."
        )

    q_data = {}
    offset = None
    while True:
        points, offset = qdrant.scroll(
            collection_name=COLLECTION_NAME,
            limit=512,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        for point in points:
            payload = point.payload or {}
            key = payload.get("document_id")
            if not key:
                raise RuntimeError("Qdrant has a point without document_id")
            q_data[key] = (
                payload.get("document_type"), payload.get("filter_group")
            )
        if offset is None:
            break

    if q_data != pg_data:
        missing_q = set(pg_data) - set(q_data)
        missing_pg = set(q_data) - set(pg_data)
        differing = [
            key for key in set(pg_data) & set(q_data)
            if pg_data[key] != q_data[key]
        ]
        raise RuntimeError(
            "Vector stores disagree: "
            f"missing in Qdrant={sorted(missing_q)[:5]}, "
            f"missing in PostgreSQL={sorted(missing_pg)[:5]}, "
            f"metadata mismatch={sorted(differing)[:5]}"
        )

    details = qdrant.get_collection(COLLECTION_NAME)
    indexed = getattr(details, "indexed_vectors_count", None)
    print("DATASET")
    print(f"  documents: {len(pg_data)} in both stores")
    print(f"  rare-filter documents: {pg_rare}/{len(pg_data)} "
          f"({100 * pg_rare / len(pg_data):.2f}%)")
    print(f"  Qdrant indexed_vectors_count: {indexed}")
    if not indexed:
        print(
            "  WARNING: Qdrant may use a full scan for ANN-mode queries "
            "on a dataset this small; do not claim HNSW was exercised."
        )
    return pg_data


def check_pg_hnsw(pg, install):
    indexes = pg.execute(
        """
        SELECT indexname, indexdef FROM pg_indexes
        WHERE schemaname = current_schema()
          AND tablename = 'vector_documents'
          AND indexdef ILIKE '%USING hnsw%'
          AND indexdef ILIKE '%vector_cosine_ops%'
        """
    ).fetchall()
    if not indexes and install:
        print("Installing explicitly requested PostgreSQL HNSW cosine index...")
        pg.execute(
            """
            CREATE INDEX IF NOT EXISTS vector_documents_embedding_hnsw_idx
            ON vector_documents USING hnsw (embedding vector_cosine_ops)
            WITH (m = 16, ef_construction = 64)
            """
        )
        pg.execute("ANALYZE vector_documents")
        indexes = pg.execute(
            """
            SELECT indexname, indexdef FROM pg_indexes
            WHERE schemaname = current_schema()
              AND tablename = 'vector_documents'
              AND indexdef ILIKE '%USING hnsw%'
              AND indexdef ILIKE '%vector_cosine_ops%'
            """
        ).fetchall()

    if not indexes:
        raise RuntimeError(
            "No PostgreSQL HNSW cosine index found. "
            "Run with --install-pg-hnsw to explicitly create one "
            "(this option changes only the PostgreSQL index)."
        )
    print("  PostgreSQL HNSW index:", indexes[0][0])
    return indexes[0][0]


def pg_query(pg, vector, *, exact, group=None, limit=K, ef=64, iterative="off",
             force_hnsw=False, explain=False):
    where = "WHERE filter_group = %s" if group is not None else ""
    sql = (
        f"SELECT id FROM vector_documents {where} "
        "ORDER BY embedding <=> %s::vector LIMIT %s"
    )
    args = ([group] if group is not None else []) + [vector, limit]

    with pg.transaction():
        if exact:
            pg.execute("SET LOCAL enable_indexscan = off")
            pg.execute("SET LOCAL enable_bitmapscan = off")
        else:
            pg.execute("SET LOCAL enable_seqscan = off")
            pg.execute("SET LOCAL enable_bitmapscan = off")
            if force_hnsw:
                # A controlled experiment: discourage the B-tree + Sort
                # plan for highly selective filters. This is *not* how the
                # default PostgreSQL planner would choose to execute it.
                pg.execute("SET LOCAL enable_sort = off")
            pg.execute("SELECT set_config('hnsw.ef_search', %s, true)
                       (str(ef),))
            if iterative != "off":
                pg.execute(
                    "SELECT set_config('hnsw.iterative_scan', %s, true)",
                    (iterative,),
                )

        if explain:
            # JSON plans let us report index names without dumping a
            # 384-component vector into the presentation evidence.
            raw = pg.execute(
                "EXPLAIN (FORMAT JSON) " + sql, args
            ).fetchone()[0]
            plan = json.loads(raw) if isinstance(raw, str) else raw
            nodes = []

            def visit(node):
                name = node["Node Type"]
                if node.get("Index Name"):
                    name += " using " + node["Index Name"]
                nodes.append(name)
                for child in node.get("Plans", []):
                    visit(child)

            visit(plan[0]["Plan"])
            return nodes

        start = time.perf_counter()
        rows = pg.execute(sql, args).fetchall()
        latency_ms = (time.perf_counter() - start) * 1000
    return [row[0] for row in rows], latency_ms


def q_query(qdrant, vector, *, exact, condition=None, limit=K, ef=64):
    start = time.perf_counter()
    points = qdrant.query_points(
        collection_name=COLLECTION_NAME,
        query=vector,
        limit=limit,
        query_filter=condition,
        search_params=models.SearchParams(exact=exact, hnsw_ef=ef),
        with_payload=["document_id"],
        with_vectors=False,
    ).points
    latency_ms = (time.perf_counter() - start) * 1000
    return [p.payload["document_id"] for p in points], latency_ms


def recall(approx, exact):
    return len(set(approx) & set(exact)) / len(exact) if exact else 1.0


def summarize(name, cases):
    print(name)
    print(f"  queries: {len(cases)}")
    for store in ("PostgreSQL", "Qdrant"):
        rec = [x[store + "_recall"] for x in cases]
        times = [x[store + "_ms"] for x in cases]
        counts = [x[store + "_returned"] for x in cases]
        print(
            f"  {store}: ANN recall@10={statistics.mean(rec):.4f}, "
            f"mean returned={statistics.mean(counts):.2f}, "
            f"mean ANN latency={statistics.mean(times):.3f} ms"
        )
    overlaps = [x["overlap"] for x in cases]
    print(f"  cross-store ANN top-10 overlap={statistics.mean(overlaps):.2f}/10")
    for x in cases:
        if x["PostgreSQL_recall"] < 1 or x["Qdrant_recall"] < 1:
            print("  non-perfect query:", x["query_id"],
                  "pg=", x["PostgreSQL_recall"],
                  "qdrant=", x["Qdrant_recall"],
                  "returned=", x["PostgreSQL_returned"],
                  x["Qdrant_returned"])
            break


def evaluate_ann(pg, qdrant, model, args):
    queries = list(BENCHMARK_QUERIES)
    if len(queries) != 20:
        raise RuntimeError("Expected 20 frozen benchmark queries")
    vectors = model.encode(
        queries, normalize_embeddings=True, show_progress_bar=False
    )
    summaries = {"unfiltered": [], "filtered": []}

    for index, embedding in enumerate(vectors, 1):
        vector = embedding.astype(np.float32).tolist()
        for filtered in (False, True):
            group = "rare" if filtered else None
            qfilter = qdrant_filter("filter_group", "rare") if filtered else None
            pg_exact, _ = pg_query(pg, vector, exact=True, group=group)
            pg_ann, pg_ms = pg_query(
                pg, vector, exact=False, group=group, ef=args.pg_ef,
                iterative=args.iterative_scan
            )
            q_exact, _ = q_query(
                qdrant, vector, exact=True, condition=qfilter
            )
            q_ann, q_ms = q_query(
                qdrant, vector, exact=False, condition=qfilter, ef=args.q_ef
            )
            entry = {
                "query_id": f"Q{index:02d}",
                "PostgreSQL_recall": recall(pg_ann, pg_exact),
                "Qdrant_recall": recall(q_ann, q_exact),
                "PostgreSQL_ms": pg_ms,
                "Qdrant_ms": q_ms,
                "PostgreSQL_returned": len(pg_ann),
                "Qdrant_returned": len(q_ann),
                "overlap": len(set(pg_ann) & set(q_ann)),
            }
            summaries["filtered" if filtered else "unfiltered"].append(entry)

    print("\nHNSW-REQUESTED SEARCH METRICS")
    print("  query count: 20; k=10; reference=each store's exact top-10")
    print("  pg hnsw.ef_search:", args.pg_ef)
    print("  pg hnsw.iterative_scan:", args.iterative_scan)
    print("  Qdrant hnsw_ef:", args.q_ef)
    summarize("UNFILTERED", summaries["unfiltered"])
    summarize("RARE FILTER (~5%)", summaries["filtered"])

    # Confirm the database planner really uses an HNSW index, rather
    # than mistakenly reporting exact SQL as approximate search.
    first_vector = vectors[0].astype(np.float32).tolist()
    for group in (None, "rare"):
        plan = pg_query(
            pg, first_vector, exact=False, group=group,
            ef=args.pg_ef, iterative=args.iterative_scan, explain=True
        )
        print(f"  PostgreSQL plan ({group or 'unfiltered'}):", plan)
        if "hnsw" not in plan.lower():
            raise RuntimeError(
                "PostgreSQL did not use HNSW for an ANN query; "
                "do not report its result as HNSW recall"
            )
    return first_vector


def evaluate_duplicates(model, args):
    cases = read_labels("duplicate_test_cases.json")
    if len(cases) != 25 or sum(c["expected_duplicate"] for c in cases) != 10:
        raise RuntimeError("Duplicate labels must contain 10 positive / 15 negative")
    texts = [text for c in cases for text in (c["text_a"], c["text_b"])]
    vectors = model.encode(
        texts, normalize_embeddings=True, show_progress_bar=False
    )
    tp = fp = fn = tn = 0
    mistakes = []
    for i, case in enumerate(cases):
        score = float(np.dot(vectors[2*i], vectors[2*i+1]))
        predicted = score >= args.duplicate_threshold
        expected = case["expected_duplicate"]
        if predicted and expected:
            tp += 1
        elif predicted and not expected:
            fp += 1
        elif not predicted and expected:
            fn += 1
        else:
            tn += 1
        if predicted != expected:
            mistakes.append((case["id"], round(score, 4), expected, predicted))
    precision = tp / (tp + fp) if tp + fp else 0
    sensitivity = tp / (tp + fn) if tp + fn else 0
    print("\nNEAR-DUPLICATE RECEIPT PAIRS")
    print("  frozen labels: 25 pairs (10 positive, 15 negative)")
    print("  fixed cosine similarity threshold:", args.duplicate_threshold)
    print(f"  TP={tp}, FP={fp}, FN={fn}, TN={tn}")
    print(f"  precision={precision:.4f}; recall={sensitivity:.4f}")
    print("  errors:", mistakes[:10])


def policy_group(policy_id):
    """IDs 001, 021, 041, 061, 081 carry repeated policy text."""
    if not policy_id.startswith("policy_"):
        return None
    number = int(policy_id.split("_")[-1])
    return ((number - 1) % 20) + 1


def evaluate_policy(pg, qdrant, model, args):
    cases = read_labels("policy_test_cases.json")
    if len(cases) != 20:
        raise RuntimeError("Expected 20 fixed policy queries")
    vectors = model.encode(
        [x["query"] for x in cases],
        normalize_embeddings=True,
        show_progress_bar=False
    )
    print("\nPOLICY RETRIEVAL (filter: document_type=policy)")
    print("  labelled queries: 20; top-k=5")
    for name in ("PostgreSQL", "Qdrant"):
        canonical_found = 0
        canonical_rr = 0.0
        group_found = 0
        group_rr = 0.0
        errors = []
        for case, embedding in zip(cases, vectors):
            vector = embedding.astype(np.float32).tolist()
            if name == "PostgreSQL":
                # Policy-only SQL results, exact table scan. This measures
                # semantic quality rather than the ANN approximation.
                sql = (
                    "SELECT id FROM vector_documents WHERE document_type = 'policy' "
                    "ORDER BY embedding <=> %s::vector LIMIT 5"
                )
                with pg.transaction():
                    pg.execute("SET LOCAL enable_indexscan = off")
                    pg.execute("SET LOCAL enable_bitmapscan = off")
                    ids = [r[0] for r in pg.execute(sql, (vector,)).fetchall()]
            else:
                ids, _ = q_query(
                    qdrant, vector, exact=True,
                    condition=qdrant_filter("document_type", "policy"), limit=5
                )
            canon = set(case["relevant_policy_ids"])
            canonical_ranks = [
                i for i, pid in enumerate(ids, 1) if pid in canon
            ]
            expected_groups = {policy_group(x) for x in canon}
            group_ranks = [
                i for i, pid in enumerate(ids, 1)
                if policy_group(pid) in expected_groups
            ]
            if canonical_ranks:
                canonical_found += 1
                canonical_rr += 1 / min(canonical_ranks)
            if group_ranks:
                group_found += 1
                group_rr += 1 / min(group_ranks)
            if not canonical_ranks:
                errors.append((case["id"], list(canon), ids))
        print(
            f"  {name}: canonical-ID recall@5={canonical_found}/20 "
            f"({canonical_found/20:.4f}), MRR={canonical_rr/20:.4f}"
        )
        print(
            f"  {name}: repeated-policy-group recall@5={group_found}/20 "
            f"({group_found/20:.4f}), MRR={group_rr/20:.4f}"
        )
        print("  canonical-ID misses (first 3):", errors[:3])
    print(
        "  Caution: 100 stored policy rows repeat 20 canonical passages. "
        "The second metric counts equivalent copies; labels name only "
        "canonical IDs."
    )


def demonstrate_business_join(pg, qdrant, vector):
    print("\nPOSTGRES JOIN vs QDRANT+POSTGRES LOOKUP")
    if pg.execute(
        "SELECT to_regclass('public.receipt_expense_mapping')"
    ).fetchone()[0] is None:
        print(
            "  SKIPPED: receipt_expense_mapping absent. "
            "Do not invent a join result or run the old hard-coded mapping "
            "script without checking its expense IDs."
        )
        return

    rows = pg.execute(
        """
        SELECT v.id, v.source_id, m.expense_id, e.amount, e.status
        FROM vector_documents AS v
        JOIN receipt_expense_mapping AS m
          ON m.receipt_document_id = v.id
        JOIN expenses AS e ON e.id = m.expense_id
        WHERE v.document_type = 'receipt'
        ORDER BY v.embedding <=> %s::vector
        LIMIT 1
        """,
        (vector,),
    ).fetchall()
    if not rows:
        print("  SKIPPED: no valid vector-receipt to expense mappings.")
        return

    document_id, source_id, expense_id, amount, status = rows[0]
    print("  PostgreSQL one-query enriched result:",
          document_id, source_id, expense_id, amount, status)
    qdrant_id = str(uuid.uuid5(uuid.NAMESPACE_URL, document_id))
    points = qdrant.retrieve(
        collection_name=COLLECTION_NAME, ids=[qdrant_id], with_payload=True
    )
    if not points:
        raise RuntimeError("Mapped document not present in Qdrant")
    payload = points[0].payload
    business = pg.execute(
        """
        SELECT e.id, e.amount, e.status
        FROM receipt_expense_mapping m
        JOIN expenses e ON e.id = m.expense_id
        WHERE m.receipt_document_id = %s
        """,
        (payload["document_id"],),
    ).fetchone()
    print("  Qdrant ID/payload lookup:", payload["document_id"],
          payload["source_id"])
    print("  PostgreSQL second business lookup:", business)
    print("  This comparison demonstrates the enrichment step, not identical "
          "SQL-vs-Qdrant nearest-neighbor ranking.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duplicate-threshold", type=float, default=0.85)
    parser.add_argument("--pg-ef", type=int, default=64)
    parser.add_argument("--q-ef", type=int, default=64)
    parser.add_argument(
        "--iterative-scan", choices=["off", "strict_order"],
        default="off"
    )
    parser.add_argument("--install-pg-hnsw", action="store_true")
    args = parser.parse_args()
    if not (0 <= args.duplicate_threshold <= 1):
        parser.error("Duplicate cosine threshold must be between 0 and 1")

    print("FINAL VECTOR EVALUATION — inspect actual live records; no synthetic metrics")
    pg = get_connection()
    pg.autocommit = True
    qdrant = get_qdrant_client()
    try:
        check_dataset(pg, qdrant)
        check_pg_hnsw(pg, args.install_pg_hnsw)
        model = SentenceTransformer(MODEL_NAME)
        print("  embedding model:", MODEL_NAME, "normalized cosine")
        first_vector = evaluate_ann(pg, qdrant, model, args)
        evaluate_duplicates(model, args)
        evaluate_policy(pg, qdrant, model, args)
        demonstrate_business_join(pg, qdrant, first_vector)
    finally:
        pg.close()


if __name__ == "__main__":
    main()
