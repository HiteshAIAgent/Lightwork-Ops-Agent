import os
from contextlib import contextmanager
from typing import Optional
from datetime import date, timedelta
from urllib.parse import urlparse
import pg8000

DATABASE_URL = os.environ["DATABASE_URL"]
_url = urlparse(DATABASE_URL)


@contextmanager
def _conn():
    conn = pg8000.connect(
        host=_url.hostname,
        port=_url.port or 5432,
        database=_url.path.lstrip("/"),
        user=_url.username,
        password=_url.password,
        ssl_context=True,
    )
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _rows(conn, sql, params=()):
    cur = conn.cursor()
    cur.execute(sql, list(params))
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _one(conn, sql, params=()):
    cur = conn.cursor()
    cur.execute(sql, list(params))
    if not cur.description:
        return None
    cols = [d[0] for d in cur.description]
    row = cur.fetchone()
    return dict(zip(cols, row)) if row else None


def _exec(conn, sql, params=()):
    cur = conn.cursor()
    cur.execute(sql, list(params) if params else None)
    return cur


def init_db():
    with _conn() as conn:
        for stmt in [
            """CREATE TABLE IF NOT EXISTS commitments (
                id          SERIAL PRIMARY KEY,
                team        TEXT NOT NULL,
                description TEXT NOT NULL,
                deadline    TEXT NOT NULL,
                owner       TEXT,
                priority    TEXT NOT NULL DEFAULT 'medium',
                depends_on  INTEGER REFERENCES commitments(id),
                created_at  TEXT NOT NULL DEFAULT TO_CHAR(NOW(),'YYYY-MM-DD HH24:MI:SS')
            )""",
            """CREATE TABLE IF NOT EXISTS updates (
                id            SERIAL PRIMARY KEY,
                commitment_id INTEGER NOT NULL REFERENCES commitments(id),
                status        TEXT NOT NULL CHECK(status IN ('on_track','at_risk','missed','completed')),
                notes         TEXT,
                updated_at    TEXT NOT NULL DEFAULT TO_CHAR(NOW(),'YYYY-MM-DD HH24:MI:SS')
            )""",
            """CREATE TABLE IF NOT EXISTS alerts (
                id          SERIAL PRIMARY KEY,
                from_role   TEXT NOT NULL,
                to_team     TEXT NOT NULL,
                message     TEXT NOT NULL,
                resolved    INTEGER NOT NULL DEFAULT 0,
                created_at  TEXT NOT NULL DEFAULT TO_CHAR(NOW(),'YYYY-MM-DD HH24:MI:SS')
            )""",
            """CREATE TABLE IF NOT EXISTS alert_responses (
                id          SERIAL PRIMARY KEY,
                alert_id    INTEGER NOT NULL REFERENCES alerts(id),
                response    TEXT NOT NULL,
                created_at  TEXT NOT NULL DEFAULT TO_CHAR(NOW(),'YYYY-MM-DD HH24:MI:SS')
            )""",
            "ALTER TABLE commitments ADD COLUMN IF NOT EXISTS priority TEXT NOT NULL DEFAULT 'medium'",
            "ALTER TABLE commitments ADD COLUMN IF NOT EXISTS depends_on INTEGER REFERENCES commitments(id)",
        ]:
            _exec(conn, stmt)


def add_commitment(team: str, description: str, deadline: str,
                   owner: Optional[str] = None, priority: str = "medium",
                   depends_on: Optional[int] = None) -> dict:
    sql = ("INSERT INTO commitments (team, description, deadline, owner, priority, depends_on)"
           " VALUES (%s,%s,%s,%s,%s,%s) RETURNING id")
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(sql, [team, description, deadline, owner, priority, depends_on])
        new_id = cur.fetchone()[0]
    return {"id": new_id, "team": team, "description": description,
            "deadline": deadline, "owner": owner, "priority": priority, "depends_on": depends_on}


def log_update(commitment_id: int, status: str, notes: Optional[str] = None) -> dict:
    with _conn() as conn:
        row = _one(conn, "SELECT id FROM commitments WHERE id = %s", (commitment_id,))
        if not row:
            return {"error": f"No commitment with id {commitment_id}"}
        _exec(conn, "INSERT INTO updates (commitment_id, status, notes) VALUES (%s,%s,%s)",
              (commitment_id, status, notes))
    return {"ok": True, "commitment_id": commitment_id, "status": status}


def get_commitments(team: Optional[str] = None, status: Optional[str] = None) -> list:
    query = """
        SELECT
            c.id, c.team, c.description, c.deadline, c.owner, c.priority, c.depends_on,
            dep.description  AS dep_description,
            dep.team         AS dep_team,
            dep.owner        AS dep_owner,
            COALESCE(dep_u.status, 'no_update') AS dep_status,
            COALESCE(u.status, 'no_update') AS latest_status,
            u.notes          AS latest_notes,
            u.updated_at     AS last_updated
        FROM commitments c
        LEFT JOIN (
            SELECT commitment_id, status, notes, updated_at
            FROM updates
            WHERE id IN (SELECT MAX(id) FROM updates GROUP BY commitment_id)
        ) u ON c.id = u.commitment_id
        LEFT JOIN commitments dep ON c.depends_on = dep.id
        LEFT JOIN (
            SELECT commitment_id, status
            FROM updates
            WHERE id IN (SELECT MAX(id) FROM updates GROUP BY commitment_id)
        ) dep_u ON dep.id = dep_u.commitment_id
    """
    params, conditions = [], []
    if team:
        conditions.append("c.team = %s")
        params.append(team)
    if status:
        if status == "no_update":
            conditions.append("u.status IS NULL")
        else:
            conditions.append("COALESCE(u.status,'no_update') = %s")
            params.append(status)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY c.deadline ASC"
    with _conn() as conn:
        return _rows(conn, query, params)


def get_stale_commitments(days_ahead: int = 7) -> list:
    today = date.today().isoformat()
    cutoff = (date.today() + timedelta(days=days_ahead)).isoformat()
    stale_since = (date.today() - timedelta(days=7)).isoformat()
    query = """
        SELECT c.id, c.team, c.description, c.deadline, c.owner, c.priority,
            COALESCE(u.status, 'no_update') AS latest_status,
            u.updated_at AS last_updated,
            CASE WHEN c.deadline < %s THEN 1 ELSE 0 END AS overdue
        FROM commitments c
        LEFT JOIN (
            SELECT commitment_id, status, updated_at
            FROM updates
            WHERE id IN (SELECT MAX(id) FROM updates GROUP BY commitment_id)
        ) u ON c.id = u.commitment_id
        WHERE c.deadline <= %s
            AND COALESCE(u.status,'no_update') NOT IN ('completed','missed')
            AND (u.updated_at IS NULL OR u.updated_at < %s)
        ORDER BY c.deadline ASC
    """
    with _conn() as conn:
        return _rows(conn, query, (today, cutoff, stale_since))


def update_commitment(commitment_id: int, description: str = None, deadline: str = None,
                      owner: str = None, priority: str = None) -> dict:
    with _conn() as conn:
        row = _one(conn, "SELECT id FROM commitments WHERE id = %s", (commitment_id,))
        if not row:
            return {"error": f"No commitment with id {commitment_id}"}
        fields = {}
        if description is not None: fields["description"] = description
        if deadline    is not None: fields["deadline"]    = deadline
        if owner       is not None: fields["owner"]       = owner
        if priority    is not None: fields["priority"]    = priority
        if fields:
            sets = ", ".join(f"{k} = %s" for k in fields)
            _exec(conn, f"UPDATE commitments SET {sets} WHERE id = %s",
                  list(fields.values()) + [commitment_id])
    return {"ok": True, "id": commitment_id}


def create_alert(from_role: str, to_team: str, message: str) -> dict:
    sql = "INSERT INTO alerts (from_role, to_team, message) VALUES (%s,%s,%s) RETURNING id"
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(sql, [from_role, to_team, message])
        new_id = cur.fetchone()[0]
    return {"id": new_id, "from_role": from_role, "to_team": to_team, "message": message}


def get_alerts(team: Optional[str] = None, include_resolved: bool = False) -> list:
    query = """
        SELECT a.id, a.from_role, a.to_team, a.message, a.resolved, a.created_at,
               r.response, r.created_at AS responded_at
        FROM alerts a
        LEFT JOIN alert_responses r ON a.id = r.alert_id
    """
    conditions, params = [], []
    if team:
        conditions.append("a.to_team = %s")
        params.append(team)
    if not include_resolved:
        conditions.append("a.resolved = 0")
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY a.created_at DESC"
    with _conn() as conn:
        return _rows(conn, query, params)


def respond_to_alert(alert_id: int, response: str) -> dict:
    with _conn() as conn:
        _exec(conn, "INSERT INTO alert_responses (alert_id, response) VALUES (%s,%s)",
              (alert_id, response))
        _exec(conn, "UPDATE alerts SET resolved = 1 WHERE id = %s", (alert_id,))
    return {"ok": True, "alert_id": alert_id}
