# Prime P1 Complete Static Authority Admission Plan

Goal: Make authority process admit the complete existing four-resource production set before its intentional unavailable stop.

Constraints: Replace static-only admission with admit_production_authority_resources. Close aggregate exactly once. Still call unavailable before consuming session key/socket/ready/execute/probe/Docker/model. No public contract change.

Task 1:

- Modify authority_process.py and test_prime_p1_authority_process.py.
- RED tests assert complete admission is invoked after config load; static-only admission is never invoked; aggregate closes once on success/failure; errors stay unavailable and no handshake side effect occurs.
- GREEN minimal replace import/call/local name/close. Run authority process/resources/socket tests, Ruff/diff; commit focused scope, independent review.

