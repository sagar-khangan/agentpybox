from agenthaven.security_audit import audit


def test_audit_is_explicit_about_missing_cgroup_enforcement():
    result = audit()
    assert result['cgroup_limits_enforced_by_agenthaven'] is False
    assert isinstance(result['cgroup_controllers'], list)
