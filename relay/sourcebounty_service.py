import hashlib
import json
import os
import sqlite3
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

DB_PATH = os.environ.get("SOURCEBOUNTY_DB_PATH", "sourcebounty.db")
PORT = int(os.environ.get("PORT", "8896"))
ARC_ESCROW_CONTRACT = os.environ.get("ARC_ESCROW_CONTRACT", "0x4a38251e67229438235B0999cEb086Cb2987b55C")
GENLAYER_JUDGE_CONTRACT = os.environ.get("GENLAYER_JUDGE_CONTRACT", "0xD98cCe08987CDb6Ca6A217FA1BD767c2EF5436aa")
ARC_RPC_URL = os.environ.get("ARC_RPC_URL", "https://rpc.testnet.arc.network")
ARC_CHAIN_ID = int(os.environ.get("ARC_CHAIN_ID", "5042002"))
GENLAYER_NETWORK = os.environ.get("GENLAYER_NETWORK", "studionet")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode("utf-8")).hexdigest()


def init_db():
    with sqlite3.connect(DB_PATH) as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS bounties (
                id TEXT PRIMARY KEY,
                creator TEXT NOT NULL,
                question TEXT NOT NULL,
                reward TEXT NOT NULL,
                deadline INTEGER NOT NULL,
                status TEXT NOT NULL,
                created_at INTEGER NOT NULL
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS answers (
                id TEXT PRIMARY KEY,
                bounty_id TEXT NOT NULL,
                responder TEXT NOT NULL,
                answer TEXT NOT NULL,
                answer_url TEXT NOT NULL,
                citation_urls TEXT NOT NULL,
                accepted INTEGER,
                verdict TEXT,
                created_at INTEGER NOT NULL
            )
            """
        )


def json_response(handler, status, payload):
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Headers", "content-type")
    handler.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def read_json(handler):
    length = int(handler.headers.get("content-length", "0"))
    if length == 0:
        return {}
    return json.loads(handler.rfile.read(length).decode("utf-8"))


class Handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        json_response(self, 200, {"ok": True})

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            json_response(
                self,
                200,
                {
                    "ok": True,
                    "arcRpcUrl": ARC_RPC_URL,
                    "arcChainId": ARC_CHAIN_ID,
                    "arcEscrowContract": ARC_ESCROW_CONTRACT,
                    "genlayerNetwork": GENLAYER_NETWORK,
                    "genlayerJudgeContract": GENLAYER_JUDGE_CONTRACT,
                },
            )
            return
        if path == "/bounties":
            with sqlite3.connect(DB_PATH) as db:
                rows = db.execute("SELECT * FROM bounties ORDER BY created_at DESC").fetchall()
            bounties = [
                {
                    "id": row[0],
                    "creator": row[1],
                    "question": row[2],
                    "reward": row[3],
                    "deadline": row[4],
                    "status": row[5],
                    "createdAt": row[6],
                }
                for row in rows
            ]
            json_response(self, 200, {"bounties": bounties})
            return
        json_response(self, 404, {"error": "not_found"})

    def do_POST(self):
        path = urlparse(self.path).path
        payload = read_json(self)
        now = int(time.time())
        if path == "/bounties":
            required = ["creator", "question", "reward", "deadline"]
            missing = [key for key in required if not payload.get(key)]
            if missing:
                json_response(self, 400, {"error": f"Missing fields: {', '.join(missing)}"})
                return
            bounty_id = "bounty_" + digest({**payload, "createdAt": now})[:16]
            with sqlite3.connect(DB_PATH) as db:
                db.execute(
                    "INSERT INTO bounties VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (bounty_id, payload["creator"], payload["question"], str(payload["reward"]), int(payload["deadline"]), "created", now),
                )
            json_response(self, 201, {"bountyId": bounty_id, "questionHash": digest(payload["question"])})
            return
        if path == "/answers":
            required = ["bountyId", "responder", "answer"]
            missing = [key for key in required if not payload.get(key)]
            if missing:
                json_response(self, 400, {"error": f"Missing fields: {', '.join(missing)}"})
                return
            answer_id = "ans_" + digest({**payload, "createdAt": now})[:16]
            citations = payload.get("citationUrls", [])
            verdict = {
                "accepted": bool(citations),
                "summary": "Relay preview only. Final judgement should be written through GenLayer Studionet.",
                "reasonCodes": ["PASS_MINIMUM_ACCEPTANCE"] if citations else ["MISSING_CITATIONS"],
                "verdictDigest": digest(payload),
            }
            with sqlite3.connect(DB_PATH) as db:
                db.execute(
                    "INSERT INTO answers VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        answer_id,
                        payload["bountyId"],
                        payload["responder"],
                        payload["answer"],
                        payload.get("answerUrl", ""),
                        json.dumps(citations),
                        1 if verdict["accepted"] else 0,
                        json.dumps(verdict),
                        now,
                    ),
                )
            json_response(self, 201, {"answerId": answer_id, "verdict": verdict})
            return
        json_response(self, 404, {"error": "not_found"})


if __name__ == "__main__":
    init_db()
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
