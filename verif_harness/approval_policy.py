"""Shared distinction between owner approval, evidence validity and availability.

Historical heads are identity only. They never authorize using an unavailable
capability, and are never substituted for a live version on a VALID node.
"""


def retain_head(data, previous):
    previous = previous or {}
    last = data.get("current") or previous.get("current") or previous.get("last_current")
    return {**data, **({"last_current": last} if last and not data.get("current") else {})}


def dependency_subject(dependencies):
    return [{**{key: value for key, value in item.items() if key != "last_current"},
             "status": "VALID",
             "current": (item.get("current") if item.get("status") == "VALID"
                         else item.get("current") or item.get("last_current"))}
            for item in dependencies]


def assessment(approved, *, blockers=(), evidence_current=True, has_history=False):
    """An approval may remain bound while execution/acceptance is blocked."""
    return {"approval_valid": bool(approved),
            "evidence_current": bool(evidence_current),
            "available": bool(approved and evidence_current and not blockers),
            "reapproval_required": bool(has_history and not approved)}
