# Historical decision evidence

From `expense-workflow-v2`, approvals require a MongoDB receipt with nonblank
required metadata and a positive total matching the expense amount. Missing or
unavailable evidence blocks approval without mutating PostgreSQL financial state;
rejections and escalations remain possible. The implementation assumes the
expense amount and receipt total refer to the same currency because expenses
do not currently store a currency field; it performs no exchange conversion.

Each new expense decision records `rule_version` and an `evidence_snapshot` JSONB value in
PostgreSQL. Both are saved in the **same transaction** as the expense status change and,
for approvals, the budget deduction. The snapshot is an observation of inputs at
decision time, not a reconstruction from today's mutable budget or graph.

## Evidence contract (version 1)

- `rule_version`: currently `expense-workflow-v2`; change when decision logic changes.
- `evidence_snapshot.schema_version`: structure of the stored JSON.
- `expense`: source ID, employee and cost centre IDs, budget ID, amount as an exact decimal
  string, date and prior expense status.
- `budget`: source ID, remaining balance **before and after**, and budget versions before
  and after this decision.
- `authorization`: graph store name, acting approver, cost centre, whether the
  authorization service accepted the acting approver (for approve/reject), selected
  escalation target and its authorization (for escalation), and the configured maximum
  delegation hops.
- `decision`: requested action, final outcome, and a stable reason code.
- `receipt`: for approvals, the receipt source ID, observed vendor, total, currency,
  receipt date, and an amount-matching check. For rejection/escalation it is NULL
  because those actions do not require receipt evidence.
- The existing `decisions.created_at` and `comment` fields hold decision time and
  human-entered explanation.

Amounts are saved as **decimal strings** to avoid loss of precision through JSON numbers.
Existing decisions predate this mechanism and retain NULL evidence and rule version;
they must not be presented as if full historical provenance were available.

**Limits:** This is a decision-time snapshot of the values checked by the workflow.
It records the Neo4j authorization boolean, **not** the relationship IDs, individual
delegation versions, or complete path that justified authorization. It captures a
MongoDB receipt observation for approvals, but not a source version or
transactionally consistent MongoDB snapshot. MongoDB changes can
race the PostgreSQL transaction; there is no cross-database atomic commit.
Vector-search candidates are not recorded. A future step can
add versioned source references if those inputs become part of the approval decision.

## Inspect evidence

```sql
SELECT id, created_at, decision, comment, rule_version, evidence_snapshot
FROM decisions
ORDER BY id DESC
LIMIT 5;
```

For an existing development database, apply the additive migration
`app/database/migrations/002_decision_evidence.sql` once. The migration is
idempotent and does not invent snapshots for older decisions.
