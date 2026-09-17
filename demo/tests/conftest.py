"""Shared fixtures.

Governed Automation keeps real state: the kill switch, exclusions, and an audit trail that the rolling
run caps count. Tests share that state with the demo, so each test starts from a known position.
"""

import pytest

from governed_automation import storage


@pytest.fixture(autouse=True)
def clean_automation_state():
    """Automation on globally, no exclusions, and an empty audit so run caps start from zero."""
    storage.connection()
    con = storage.cursor()
    con.execute("delete from automation_controls where scope_type != 'global'")
    storage.set_automation_enabled("global", None, True, "test reset")
    con.execute("delete from automation_exclusions")
    con.execute("delete from fact_action_audit")
    yield
