import sqlite3
from pathlib import Path
from datetime import date, timedelta
from typing import Optional

DB_PATH = Path(__file__).parent / "lightwork.db"


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS commitments (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                team        TEXT NOT NULL,
                description TEXT NOT NULL,
                deadline    TEXT NOT NULL,
                owner       TEXT,
                priority    TEXT NOT NULL DEFAULT 'medium',
                depends_on  INTEGER REFERENCES commitments(id),
                created_at  TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS updates (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                commitment_id INTEGER NOT NULL REFERENCES commitments(id),
                status        TEXT NOT NULL
                                  CHECK(status IN ('on_track','at_risk','missed','completed')),
                notes         TEXT,
                updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS alerts (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                from_role   TEXT NOT NULL,
                to_team     TEXT NOT NULL,
                message     TEXT NOT NULL,
                resolved    INTEGER NOT NULL DEFAULT 0,
                created_at  TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS alert_responses (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                alert_id    INTEGER NOT NULL REFERENCES alerts(id),
                response    TEXT NOT NULL,
                created_at  TEXT NOT NULL DEFAULT (datetime('now'))
            );
        """)
    with _conn() as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(commitments)").fetchall()]
        if 'priority' not in cols:
            conn.execute("ALTER TABLE commitments ADD COLUMN priority TEXT NOT NULL DEFAULT 'medium'")
        if 'depends_on' not in cols:
            conn.execute("ALTER TABLE commitments ADD COLUMN depends_on INTEGER REFERENCES commitments(id)")


def add_commitment(team: str, description: str, deadline: str,
                   owner: Optional[str] = None, priority: str = 'medium',
                   depends_on: Optional[int] = None) -> dict:
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO commitments (team, description, deadline, owner, priority, depends_on) VALUES (?,?,?,?,?,?)",
            (team, description, deadline, owner, priority, depends_on),
        )
        return {"id": cur.lastrowid, "team": team, "description": description,
                "deadline": deadline, "owner": owner, "priority": priority, "depends_on": depends_on}


def log_update(commitment_id: int, status: str, notes: Optional[str] = None) -> dict:
    with _conn() as conn:
        row = conn.execute("SELECT id FROM commitments WHERE id = ?", (commitment_id,)).fetchone()
        if not row:
            return {"error": f"No commitment with id {commitment_id}"}
        conn.execute(
            "INSERT INTO updates (commitment_id, status, notes) VALUES (?,?,?)",
            (commitment_id, status, notes),
        )
        return {"ok": True, "commitment_id": commitment_id, "status": status}


def get_commitments(team: Optional[str] = None, status: Optional[str] = None) -> list:
    with _conn() as conn:
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
            conditions.append("c.team = ?")
            params.append(team)
        if status:
            if status == "no_update":
                conditions.append("u.status IS NULL")
            else:
                conditions.append("COALESCE(u.status,'no_update') = ?")
                params.append(status)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY c.deadline ASC"
        return [dict(r) for r in conn.execute(query, params).fetchall()]


def get_stale_commitments(days_ahead: int = 7) -> list:
    cutoff = (date.today() + timedelta(days=days_ahead)).isoformat()
    stale_since = (date.today() - timedelta(days=7)).isoformat()
    with _conn() as conn:
        query = """
            SELECT c.id, c.team, c.description, c.deadline, c.owner, c.priority,
                COALESCE(u.status, 'no_update') AS latest_status,
                u.updated_at AS last_updated,
                CASE WHEN c.deadline < date('now') THEN 1 ELSE 0 END AS overdue
            FROM commitments c
            LEFT JOIN (
                SELECT commitment_id, status, updated_at
                FROM updates
                WHERE id IN (SELECT MAX(id) FROM updates GROUP BY commitment_id)
            ) u ON c.id = u.commitment_id
            WHERE c.deadline <= ?
                AND COALESCE(u.status,'no_update') NOT IN ('completed','missed')
                AND (u.updated_at IS NULL OR u.updated_at < ?)
            ORDER BY c.deadline ASC
        """
        return [dict(r) for r in conn.execute(query, (cutoff, stale_since)).fetchall()]


def update_commitment(commitment_id: int, description: str = None, deadline: str = None,
                      owner: str = None, priority: str = None) -> dict:
    with _conn() as conn:
        row = conn.execute("SELECT id FROM commitments WHERE id = ?", (commitment_id,)).fetchone()
        if not row:
            return {"error": f"No commitment with id {commitment_id}"}
        fields = {}
        if description is not None: fields['description'] = description
        if deadline    is not None: fields['deadline']    = deadline
        if owner       is not None: fields['owner']       = owner
        if priority    is not None: fields['priority']    = priority
        if fields:
            sets = ', '.join(f"{k} = ?" for k in fields)
            conn.execute(f"UPDATE commitments SET {sets} WHERE id = ?", list(fields.values()) + [commitment_id])
        return {"ok": True, "id": commitment_id}


def create_alert(from_role: str, to_team: str, message: str) -> dict:
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO alerts (from_role, to_team, message) VALUES (?,?,?)",
            (from_role, to_team, message),
        )
        return {"id": cur.lastrowid, "from_role": from_role, "to_team": to_team, "message": message}


def get_alerts(team: Optional[str] = None, include_resolved: bool = False) -> list:
    with _conn() as conn:
        query = """
            SELECT a.id, a.from_role, a.to_team, a.message, a.resolved, a.created_at,
                   r.response, r.created_at AS responded_at
            FROM alerts a
            LEFT JOIN alert_responses r ON a.id = r.alert_id
        """
        conditions, params = [], []
        if team:
            conditions.append("a.to_team = ?")
            params.append(team)
        if not include_resolved:
            conditions.append("a.resolved = 0")
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY a.created_at DESC"
        return [dict(r) for r in conn.execute(query, params).fetchall()]


def respond_to_alert(alert_id: int, response: str) -> dict:
    with _conn() as conn:
        conn.execute("INSERT INTO alert_responses (alert_id, response) VALUES (?,?)", (alert_id, response))
        conn.execute("UPDATE alerts SET resolved = 1 WHERE id = ?", (alert_id,))
        return {"ok": True, "alert_id": alert_id}
