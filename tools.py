import json
from anthropic import beta_tool
import db


@beta_tool
def add_commitment(team: str, description: str, deadline: str,
                   owner: str = "", priority: str = "medium", depends_on_id: int = 0) -> str:
    """Add a new team commitment or deliverable with a deadline.

    Args:
        team: Team name — Engineering, Commercial, Product, or Operations.
        description: What the team is committing to deliver.
        deadline: Deadline in YYYY-MM-DD format.
        owner: Optional name of the person responsible.
        priority: Priority level — high, medium, or low.
        depends_on_id: Optional ID of another commitment this one is blocked by. Use 0 for none.
    """
    dep = int(depends_on_id) if depends_on_id else None
    return json.dumps(db.add_commitment(team, description, deadline, owner or None, priority, dep))


@beta_tool
def log_update(commitment_id: int, status: str, notes: str = "") -> str:
    """Log a status update for a commitment.

    Args:
        commitment_id: ID of the commitment to update.
        status: Current status — on_track, at_risk, missed, or completed.
        notes: Optional context about the current status.
    """
    return json.dumps(db.log_update(int(commitment_id), status, notes or None))


@beta_tool
def list_commitments(team: str = "", status: str = "") -> str:
    """List commitments with their latest status and dependency links.

    Args:
        team: Filter by team name. Leave empty for all teams.
        status: Filter by status (on_track, at_risk, missed, completed, no_update). Leave empty for all.
    """
    return json.dumps(db.get_commitments(team or None, status or None))


@beta_tool
def get_stale_commitments(days_ahead: int = 7) -> str:
    """Find commitments approaching their deadline with no update logged in the past 7 days.

    Args:
        days_ahead: How many days ahead to look for approaching deadlines. Default is 7.
    """
    return json.dumps(db.get_stale_commitments(int(days_ahead)))
