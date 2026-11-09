class BudgetConflict(Exception):
    """The budget version changed or an atomic update failed."""


class WorkflowError(Exception):
    """The expense cannot be processed in its current state."""