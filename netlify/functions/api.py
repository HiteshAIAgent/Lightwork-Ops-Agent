import json
import db
from agent import run

db.init_db()

CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, PATCH, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
}


def handler(event, context):
    method = event.get("httpMethod", "GET")
    path = (event.get("path") or "/").rstrip("/")
    qs = event.get("queryStringParameters") or {}

    body = {}
    if event.get("body"):
        try:
            body = json.loads(event["body"])
        except Exception:
            pass

    if method == "OPTIONS":
        return {"statusCode": 200, "headers": CORS, "body": ""}

    try:
        result = _route(method, path, body, qs)
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json", **CORS},
            "body": json.dumps(result),
        }
    except Exception as e:
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json", **CORS},
            "body": json.dumps({"error": str(e)}),
        }


def _route(method, path, body, qs):
    if method == "GET" and path == "/commitments":
        return db.get_commitments(qs.get("team") or None, qs.get("status") or None)

    if method == "GET" and path == "/alerts":
        return db.get_alerts(qs.get("team") or None, include_resolved=False)

    if method == "POST" and path == "/chat":
        return {"response": run(body.get("message", ""), body.get("history", []))}

    if method == "POST" and path == "/commitments":
        result = db.add_commitment(
            body["team"], body["description"], body["deadline"],
            body.get("owner") or None, body.get("priority", "medium"),
            body.get("depends_on"),
        )
        if body.get("notes"):
            db.log_update(result["id"], "on_track", body["notes"])
        return result

    if method == "PATCH" and path.startswith("/commitments/"):
        commitment_id = int(path.split("/")[-1])
        result = {}
        if any([body.get("description"), body.get("deadline"),
                body.get("owner") is not None, body.get("priority")]):
            result["commitment"] = db.update_commitment(
                commitment_id,
                description=body.get("description"),
                deadline=body.get("deadline"),
                owner=body.get("owner"),
                priority=body.get("priority"),
            )
        if body.get("status"):
            result["update"] = db.log_update(commitment_id, body["status"], body.get("notes") or None)
        elif body.get("notes"):
            latest = db.get_commitments()
            c = next((x for x in latest if x["id"] == commitment_id), None)
            if c:
                status = c["latest_status"] if c["latest_status"] != "no_update" else "on_track"
                result["update"] = db.log_update(commitment_id, status, body["notes"])
        return result

    if method == "POST" and path == "/alerts":
        return db.create_alert(body["from_role"], body["to_team"], body["message"])

    if method == "POST" and path.endswith("/respond"):
        alert_id = int(path.split("/")[-2])
        return db.respond_to_alert(alert_id, body["response"])

    return {"error": "not found"}
