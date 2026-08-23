def test_pytest_runs():
    assert True


def test_sabotage_deliberately_failing_ci_gate_demo():
    # Phase 8 sabotage exercise, half 1 (see SESSIONS.md): a deliberately
    # failing test, pushed on a throwaway branch, opened as a real PR,
    # to confirm CI actually blocks it before this ever reaches `main`.
    # Reverted before merge — this assertion should never survive to a
    # real commit on `main`.
    assert False, "sabotage exercise: this failure is intentional"
