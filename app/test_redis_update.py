
from app.services.approver_cache import (
    cache_approver_chain,
    get_cached_approver_chain,
    invalidate_approver_chain,
)


def main():
    employee_id = 1

    # Original delegation: Alice can send approvals through Bob and Carol.
    original_chain = [2, 3]

    cache_approver_chain(
        employee_id,
        original_chain,
        source_id="delegation_employee_1",
    )

    print("1. Original Redis cache:")
    print(get_cached_approver_chain(employee_id))

    # Simulate revoking Bob's delegation in the source system.
    updated_chain = [3]

    print("\n2. Delegation revoked in source system.")
    print("New source chain:", updated_chain)

    print("\n3. Redis before refresh (stale):")
    print(get_cached_approver_chain(employee_id))

    # Invalidate the derived Redis data.
    invalidate_approver_chain(employee_id)

    print("\n4. Redis after invalidation:")
    print(get_cached_approver_chain(employee_id))

    # Rebuild the cache from the updated source data.
    cache_approver_chain(
        employee_id,
        updated_chain,
        source_id="delegation_employee_1",
    )

    print("\n5. Redis after refresh:")
    print(get_cached_approver_chain(employee_id))


if __name__ == "__main__":
    main()
