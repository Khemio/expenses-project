class BudgetConflict(Exception):
    """The budget version changed or an atomic update failed."""


class WorkflowError(Exception):
    """The expense cannot be processed in its current state."""

class UnauthorizedApprover(WorkflowError):
    """The employee lacks permission for the requested action."""

class ExpenseNotFound(WorkflowError):
    """The requested expense does not exist."""

class SelfApprovalForbidden(UnauthorizedApprover):
    """An employee cannot decide their own expense."""

class MissingReceiptEvidence(WorkflowError):
    """Approval requires a usable MongoDB receipt for this expense."""


class ReceiptEvidenceUnavailable(WorkflowError):
    """Receipt source cannot be queried; do not approve on stale assumptions."""
