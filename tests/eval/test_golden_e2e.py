from evals.runner import run_eval


def test_offline_golden_cases_all_pass_against_a_real_database():
    report = run_eval(mode="offline")
    failed = [case for case in report["cases"] if not case["passed"]]
    assert not failed, "\n".join(f"{case['id']}: {case['failures']}" for case in failed)
    assert report["invariant_problems"] == []
    assert report["summary"]["cases"] >= 30