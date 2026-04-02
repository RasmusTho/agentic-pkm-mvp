from scripts.reconcile_project_status import desired_pr_status


def test_desired_pr_status_open_pr_is_in_progress() -> None:
    assert desired_pr_status({"state": "OPEN", "mergedAt": None}, None) == "In Progress"


def test_desired_pr_status_closed_unmerged_pr_is_done() -> None:
    assert desired_pr_status({"state": "CLOSED", "mergedAt": None}, None) == "Done"


def test_desired_pr_status_explicit_status_wins() -> None:
    assert (
        desired_pr_status({"state": "CLOSED", "mergedAt": None}, "Review")
        == "Review"
    )
