class BudgetConflict(Exception):
    """The budget version changed or an atomic update failed."""


class WorkflowError(Exception):
    """The expense cannot be processed in its current state."""

class UnauthorizedApprover(WorkflowError):
    """The employee lacks permission for the requested action."""

class ExpenseNotFound(WorkflowError):
    """The requested expense does not exist."""