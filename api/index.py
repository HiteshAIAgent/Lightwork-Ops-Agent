import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from http.server import BaseHTTPRequestHandler
import json
import urllib.parse
import db
from agent import run

db.init_db()


def _body(handler):
    length = int(handler.headers.get("Content-Length", 0))
    return json.loads(handler.rfile.read(length)) if length else {}


def _json(handler, code, data):
    body = json.dumps(data).encode()
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Methods", "*")
    handler.send_header("Access-Control-Allow-Headers", "*")
    handler.end_headers()
    handler.wfile.write(body)


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        qs = dict(urllib.parse.parse_qsl(parsed.query))
        path = parsed.path.rstrip("/")

        if path == "/commitments":
            _json(self, 200, db.get_commitments(qs.get("team") or None, qs.get("status") or None))
        elif path == "/alerts":
            _json(self, 200, db.get_alerts(qs.get("team") or None, include_resolved=False))
        else:
            _json(self, 404, {"error": "not found"})

    def do_POST(self):
        path = self.path.rstrip("/")
        body = _body(self)

        if path == "/chat":
            response = run(body.get("message", ""), body.get("history", []))
            _json(self, 200, {"response": response})
        elif path == "/commitments":
            result = db.add_commitment(
                body["team"], body["description"], body["deadline"],
                body.get("owner") or None, body.get("priority", "medium"),
                body.get("depends_on")
            )
            if body.get("notes"):
                db.log_update(result["id"], "on_track", body["notes"])
            _json(self, 200, result)
        elif path == "/alerts":
            _json(self, 200, db.create_alert(body["from_role"], body["to_team"], body["message"]))
        elif path.endswith("/respond"):
            alert_id = int(path.split("/")[-2])
            _json(self, 200, db.respond_to_alert(alert_id, body["response"]))
        else:
            _json(self, 404, {"error": "not found"})

    def do_PATCH(self):
        parts = self.path.rstrip("/").split("/")
        body = _body(self)
        commitment_id = int(parts[-1])
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

        _json(self, 200, result)

    def log_message(self, *args):
        pass
