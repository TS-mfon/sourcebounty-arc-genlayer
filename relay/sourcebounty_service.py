import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from web3 import Web3

DB_PATH = os.environ.get("SOURCEBOUNTY_DB_PATH", "sourcebounty.db")
PORT = int(os.environ.get("PORT", "8896"))
ARC_ESCROW_CONTRACT = os.environ.get("ARC_ESCROW_CONTRACT", "0x4a38251e67229438235B0999cEb086Cb2987b55C")
GENLAYER_JUDGE_CONTRACT = os.environ.get("GENLAYER_JUDGE_CONTRACT", "0xD98cCe08987CDb6Ca6A217FA1BD767c2EF5436aa")
ARC_RPC_URL = os.environ.get("ARC_RPC_URL", "https://rpc.testnet.arc.network")
ARC_CHAIN_ID = int(os.environ.get("ARC_CHAIN_ID", "5042002"))
GENLAYER_NETWORK = os.environ.get("GENLAYER_NETWORK", "studionet")
BLOCKED_CITATION_HOSTS = ("x.com", "twitter.com", "instagram.com", "tiktok.com", "facebook.com")
RELAY_VERSION = "sourcebounty-ui-v8"
GENLAYER_CLI = os.environ.get("GENLAYER_CLI", "genlayer")
GENLAYER_PASSWORD = os.environ.get("GENLAYER_PASSWORD", "")
RELAY_PRIVATE_KEY = os.environ.get("RELAY_PRIVATE_KEY", os.environ.get("PRIVATE_KEY", ""))
RUBRIC_VERSION = os.environ.get("RUBRIC_VERSION", "v1")

ESCROW_ABI = [
    {
        "inputs": [
            {"internalType": "uint256", "name": "bountyId", "type": "uint256"},
            {"internalType": "bool", "name": "accepted", "type": "bool"},
            {"internalType": "bytes32", "name": "verdictDigest", "type": "bytes32"},
        ],
        "name": "recordVerdict",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "uint256", "name": "bountyId", "type": "uint256"}],
        "name": "releaseReward",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
]


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
                created_at INTEGER NOT NULL,
                onchain_bounty_id TEXT DEFAULT '',
                funding_tx_hash TEXT DEFAULT ''
            )
            """
        )
        add_column(db, "bounties", "onchain_bounty_id", "TEXT DEFAULT ''")
        add_column(db, "bounties", "funding_tx_hash", "TEXT DEFAULT ''")
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
                created_at INTEGER NOT NULL,
                answer_tx_hash TEXT DEFAULT ''
            )
            """
        )
        add_column(db, "answers", "answer_tx_hash", "TEXT DEFAULT ''")


def add_column(db, table, column, definition):
    columns = [row[1] for row in db.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in columns:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def validate_optional_urls(urls):
    if not urls:
        return []
    problems = []
    for raw_url in urls:
        url = str(raw_url).strip()
        parsed = urlparse(url)
        hostname = (parsed.hostname or "").lower()
        if parsed.scheme not in ("http", "https") or not hostname:
            problems.append({"url": url, "reason": "Use a full http(s) URL."})
            continue
        if hostname in BLOCKED_CITATION_HOSTS or hostname.endswith(tuple(f".{host}" for host in BLOCKED_CITATION_HOSTS)):
            problems.append({"url": url, "reason": "GenLayer may not be able to access gated/social links. Add a public mirror or raw citation link."})
            continue
        try:
            request = Request(url, method="HEAD", headers={"User-Agent": "SourceBounty-Link-Check/1.0"})
            with urlopen(request, timeout=6) as response:
                if response.status >= 400:
                    problems.append({"url": url, "reason": f"URL returned HTTP {response.status}."})
        except Exception as exc:
            problems.append({"url": url, "reason": f"GenLayer cannot access this link from the relay: {exc}"})
    return problems


def run_genlayer(args, timeout=180):
    if not shutil.which(GENLAYER_CLI):
        raise RuntimeError("GenLayer CLI is not installed on the relay.")
    stdin = f"{GENLAYER_PASSWORD}\n" if GENLAYER_PASSWORD else None
    result = subprocess.run([GENLAYER_CLI, *args], input=stdin, text=True, capture_output=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "GenLayer command failed").strip())
    return result.stdout.strip()


def extract_json_candidates(raw):
    candidates = []
    stack = []
    start = None
    for index, char in enumerate(raw):
        if char == "{":
            if not stack:
                start = index
            stack.append(char)
        elif char == "}" and stack:
            stack.pop()
            if not stack and start is not None:
                candidates.append(raw[start : index + 1])
                start = None
    return candidates


def extract_json_object(raw):
    for candidate in reversed(extract_json_candidates(raw)):
        try:
            return json.loads(candidate)
        except Exception:
            continue
    raise RuntimeError(f"Could not parse GenLayer verdict output: {raw}")


def maybe_extract_verdict(raw):
    try:
        data = extract_json_object(raw)
    except Exception:
        data = None
    if isinstance(data, dict) and {"accepted", "verdictDigest"}.issubset(data.keys()):
        return data
    return extract_readable_verdict(raw)


def extract_readable_verdict(raw):
    readable_matches = re.findall(r"readable:\s*'([^']+)'", raw, flags=re.S)
    for readable in reversed(readable_matches):
        if '"accepted":' not in readable or '"verdictDigest":' not in readable:
            continue
        accepted_match = re.search(r'"accepted":(true|false)', readable)
        verdict_digest_match = re.search(r'"verdictDigest":"([^"]+)"', readable)
        if not accepted_match or not verdict_digest_match:
            continue
        reason_codes_match = re.search(r'"reasonCodes":\[(.*?)\]', readable)
        reason_codes = re.findall(r'"([^"]+)"', reason_codes_match.group(1)) if reason_codes_match else []
        verdict = {
            "accepted": accepted_match.group(1) == "true",
            "summary": extract_readable_field(readable, "summary") or "GenLayer returned a verdict.",
            "reasonCodes": reason_codes,
            "evidenceDigest": extract_readable_field(readable, "evidenceDigest") or "",
            "verdictDigest": verdict_digest_match.group(1),
        }
        answer_id = extract_readable_field(readable, "answerId")
        bounty_id = extract_readable_field(readable, "bountyId")
        if answer_id:
            verdict["answerId"] = answer_id
        if bounty_id:
            verdict["bountyId"] = bounty_id
        return verdict
    return None


def extract_readable_field(readable, field):
    match = re.search(rf'"{re.escape(field)}":"([^"]*)"', readable)
    return match.group(1) if match else None


def evaluate_with_genlayer(bounty_id, answer_id, question, answer, answer_url, citations):
    write_output = run_genlayer(
        [
            "write",
            GENLAYER_JUDGE_CONTRACT,
            "evaluate_answer",
            "--args",
            bounty_id,
            answer_id,
            question,
            answer,
            answer_url or "",
            json.dumps(citations),
            RUBRIC_VERSION,
        ],
        timeout=300,
    )
    genlayer_tx_hash = ""
    write_verdict = maybe_extract_verdict(write_output)
    if write_verdict:
        write_verdict["genlayerTxHash"] = genlayer_tx_hash
        return write_verdict
    tx_hash_match = re.search(r"0x[a-fA-F0-9]{64}", write_output)
    if tx_hash_match:
        genlayer_tx_hash = tx_hash_match.group(0)
        try:
            receipt_output = run_genlayer(["receipt", genlayer_tx_hash, "--status", "FINALIZED", "--retries", "60", "--interval", "3000"], timeout=240)
            receipt_verdict = maybe_extract_verdict(receipt_output)
            if receipt_verdict:
                receipt_verdict["genlayerTxHash"] = genlayer_tx_hash
                return receipt_verdict
        except Exception as exc:
            last_receipt_error = exc
        else:
            last_receipt_error = None
    else:
        last_receipt_error = "GenLayer write output did not include a transaction hash."
    last_error = None
    for _ in range(18):
        try:
            verdict_raw = run_genlayer(["call", GENLAYER_JUDGE_CONTRACT, "get_verdict", "--args", bounty_id], timeout=120)
            verdict = extract_json_object(verdict_raw)
            verdict["genlayerTxHash"] = genlayer_tx_hash
            return verdict
        except Exception as exc:
            last_error = exc
            time.sleep(10)
    raise RuntimeError(f"GenLayer verdict was not available after evaluation. receipt={last_receipt_error}; read={last_error}; writeOutput={write_output[:1200]}")


def bytes32_from_digest(value):
    clean = str(value or "").removeprefix("0x")
    if len(clean) == 64 and re.fullmatch(r"[0-9a-fA-F]{64}", clean):
        return "0x" + clean
    return Web3.keccak(text=str(value)).hex()


def send_arc_tx(function_name, *args):
    if not RELAY_PRIVATE_KEY:
        raise RuntimeError("Relay private key is not configured; cannot write Arc verdict or reward.")
    web3 = Web3(Web3.HTTPProvider(ARC_RPC_URL))
    if not web3.is_connected():
        raise RuntimeError("Arc RPC is unavailable.")
    account = web3.eth.account.from_key(RELAY_PRIVATE_KEY)
    contract = web3.eth.contract(address=Web3.to_checksum_address(ARC_ESCROW_CONTRACT), abi=ESCROW_ABI)
    tx = getattr(contract.functions, function_name)(*args).build_transaction(
        {
            "from": account.address,
            "nonce": web3.eth.get_transaction_count(account.address),
            "chainId": ARC_CHAIN_ID,
            "gasPrice": web3.eth.gas_price,
        }
    )
    tx.setdefault("gas", web3.eth.estimate_gas(tx))
    signed = account.sign_transaction(tx)
    tx_hash = web3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
    if receipt.status != 1:
        raise RuntimeError(f"Arc transaction {function_name} failed: {tx_hash.hex()}")
    return tx_hash.hex()


def settle_answer_async(answer_id, bounty_id, onchain_bounty_id, question, answer, answer_url, citations):
    try:
        verdict = evaluate_with_genlayer(bounty_id, answer_id, question, answer, answer_url, citations)
        record_tx_hash = send_arc_tx("recordVerdict", int(onchain_bounty_id), bool(verdict["accepted"]), bytes32_from_digest(verdict["verdictDigest"]))
        reward_tx_hash = send_arc_tx("releaseReward", int(onchain_bounty_id)) if verdict["accepted"] else ""
        verdict["recordTxHash"] = record_tx_hash
        verdict["rewardTxHash"] = reward_tx_hash
        verdict["settlementStatus"] = "reward_released" if verdict["accepted"] else "verdict_recorded_no_reward"
        status = "rewarded" if verdict["accepted"] else "rejected"
        accepted = 1 if verdict["accepted"] else 0
    except Exception as exc:
        verdict = {"accepted": False, "summary": f"GenLayer/Arc settlement failed: {exc}", "reasonCodes": ["SETTLEMENT_FAILED"], "verdictDigest": digest({"answerId": answer_id, "error": str(exc)})}
        status = "settlement_failed"
        accepted = 0
    with sqlite3.connect(DB_PATH) as db:
        db.execute("UPDATE answers SET accepted = ?, verdict = ? WHERE id = ?", (accepted, json.dumps(verdict), answer_id))
        db.execute("UPDATE bounties SET status = ? WHERE id = ?", (status, bounty_id))


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
                    "relayVersion": RELAY_VERSION,
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
                    "onchainBountyId": row[7] if len(row) > 7 else "",
                    "fundingTxHash": row[8] if len(row) > 8 else "",
                }
                for row in rows
            ]
            json_response(self, 200, {"bounties": bounties})
            return
        if path == "/answers":
            with sqlite3.connect(DB_PATH) as db:
                rows = db.execute("SELECT * FROM answers ORDER BY created_at DESC").fetchall()
            answers = [
                {
                    "id": row[0],
                    "bountyId": row[1],
                    "responder": row[2],
                    "answer": row[3],
                    "answerUrl": row[4],
                    "citationUrls": json.loads(row[5]),
                    "accepted": row[6],
                    "verdict": json.loads(row[7]) if row[7] else None,
                    "createdAt": row[8],
                    "answerTxHash": row[9] if len(row) > 9 else "",
                }
                for row in rows
            ]
            json_response(self, 200, {"answers": answers})
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
            status = "funded" if payload.get("fundingTxHash") else "created"
            with sqlite3.connect(DB_PATH) as db:
                db.execute(
                    "INSERT INTO bounties VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        bounty_id,
                        payload["creator"],
                        payload["question"],
                        str(payload["reward"]),
                        int(payload["deadline"]),
                        status,
                        now,
                        str(payload.get("onchainBountyId", "")),
                        str(payload.get("fundingTxHash", "")),
                    ),
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
            url_problems = validate_optional_urls(citations)
            if url_problems:
                json_response(self, 400, {"error": "One or more citation links cannot be accessed by GenLayer.", "urlProblems": url_problems})
                return
            with sqlite3.connect(DB_PATH) as db:
                bounty = db.execute("SELECT * FROM bounties WHERE id = ?", (payload["bountyId"],)).fetchone()
            if not bounty:
                json_response(self, 404, {"error": "Bounty not found."})
                return
            onchain_bounty_id = payload.get("onchainBountyId") or (bounty[7] if len(bounty) > 7 else "")
            if not onchain_bounty_id:
                json_response(self, 400, {"error": "Missing on-chain bounty ID; create and fund the bounty before submitting an answer."})
                return
            verdict = {
                "accepted": None,
                "summary": "GenLayer evaluation started. The relay will record the verdict on Arc and release the reward only if accepted.",
                "reasonCodes": ["EVALUATION_STARTED"],
                "verdictDigest": digest({"answerId": answer_id, "status": "started"}),
            }
            with sqlite3.connect(DB_PATH) as db:
                db.execute(
                    """
                    INSERT INTO answers (
                        id, bounty_id, responder, answer, answer_url, citation_urls,
                        accepted, verdict, created_at, answer_tx_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        answer_id,
                        payload["bountyId"],
                        payload["responder"],
                        payload["answer"],
                        payload.get("answerUrl", ""),
                        json.dumps(citations),
                        None,
                        json.dumps(verdict),
                        now,
                        str(payload.get("answerTxHash", "")),
                    ),
                )
                db.execute("UPDATE bounties SET status = ? WHERE id = ?", ("evaluating", payload["bountyId"]))
            threading.Thread(
                target=settle_answer_async,
                args=(answer_id, payload["bountyId"], onchain_bounty_id, bounty[2], payload["answer"], payload.get("answerUrl", ""), citations),
                daemon=True,
            ).start()
            json_response(self, 202, {"answerId": answer_id, "verdict": verdict, "settlementStatus": "started"})
            return
        json_response(self, 404, {"error": "not_found"})


if __name__ == "__main__":
    init_db()
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
