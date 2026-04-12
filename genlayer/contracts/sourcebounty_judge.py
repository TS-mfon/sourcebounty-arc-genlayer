# { "Depends": "py-genlayer:test" }

import hashlib
import json
import re
from dataclasses import dataclass

from genlayer import *

ERROR_EXPECTED = "[EXPECTED]"
ERROR_TRANSIENT = "[TRANSIENT]"

ALLOWED_REASON_CODES = {
    "MISSING_ANSWER",
    "MISSING_CITATIONS",
    "QUESTION_MISMATCH",
    "UNSUPPORTED_CLAIMS",
    "PASS_MINIMUM_ACCEPTANCE",
}


def canonical_text(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip()).lower()


def keywords(value: str) -> set[str]:
    normalized = re.sub(r"[^a-zA-Z0-9 ]+", " ", value or "").lower()
    return {token for token in normalized.split() if len(token) > 3}


def canonical_codes(reason_codes: list[str]) -> list[str]:
    return sorted({code for code in reason_codes if code in ALLOWED_REASON_CODES})


def digest_payload(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


@allow_storage
@dataclass
class SourceBountyVerdict:
    bounty_id: str
    answer_id: str
    accepted: bool
    summary: str
    evidence_digest: str
    verdict_digest: str
    reason_codes_json: str


class SourceBountyJudge(gl.Contract):
    rubric_version: str
    verdicts: TreeMap[str, SourceBountyVerdict]

    def __init__(self, rubric_version: str):
        self.rubric_version = rubric_version

    @gl.public.view
    def get_rubric_version(self) -> str:
        return self.rubric_version

    @gl.public.view
    def get_verdict(self, bounty_id: str) -> dict:
        verdict = self.verdicts[bounty_id]
        return {
            "bountyId": verdict.bounty_id,
            "answerId": verdict.answer_id,
            "accepted": verdict.accepted,
            "summary": verdict.summary,
            "evidenceDigest": verdict.evidence_digest,
            "verdictDigest": verdict.verdict_digest,
            "reasonCodes": json.loads(verdict.reason_codes_json),
        }

    @gl.public.write
    def evaluate_answer(
        self,
        bounty_id: str,
        answer_id: str,
        question: str,
        answer_text: str,
        answer_url: str,
        citation_urls_json: str,
        rubric_version: str,
    ) -> dict:
        if not bounty_id or not answer_id or not question:
            raise gl.vm.UserError(f"{ERROR_EXPECTED} Missing required bounty fields")
        if rubric_version != self.rubric_version:
            raise gl.vm.UserError(f"{ERROR_EXPECTED} Unsupported rubric version")

        def leader_fn():
            return self._evaluate_once(bounty_id, answer_id, question, answer_text, answer_url, citation_urls_json)

        def validator_fn(leaders_res: gl.vm.Result) -> bool:
            if not isinstance(leaders_res, gl.vm.Return):
                return self._handle_leader_error(leaders_res, leader_fn)
            leader_result = leaders_res.calldata
            validator_result = leader_fn()
            return (
                validator_result["accepted"] == leader_result["accepted"]
                and canonical_codes(validator_result["reasonCodes"])
                == canonical_codes(leader_result["reasonCodes"])
            )

        verdict = gl.vm.run_nondet_unsafe(leader_fn, validator_fn)
        self.verdicts[bounty_id] = SourceBountyVerdict(
            bounty_id=bounty_id,
            answer_id=answer_id,
            accepted=verdict["accepted"],
            summary=verdict["summary"],
            evidence_digest=verdict["evidenceDigest"],
            verdict_digest=verdict["verdictDigest"],
            reason_codes_json=json.dumps(canonical_codes(verdict["reasonCodes"])),
        )
        return verdict

    def _evaluate_once(
        self,
        bounty_id: str,
        answer_id: str,
        question: str,
        answer_text: str,
        answer_url: str,
        citation_urls_json: str,
    ) -> dict:
        citation_urls = self._parse_json_array(citation_urls_json)
        answer_body = answer_text
        reason_codes: list[str] = []

        if not canonical_text(answer_body) and not canonical_text(answer_url):
            reason_codes.append("MISSING_ANSWER")
        if not citation_urls:
            reason_codes.append("MISSING_CITATIONS")
        if not answer_body and answer_url:
            answer_body = self._fetch_url_text(answer_url)

        question_terms = keywords(question)
        answer_terms = keywords(answer_body)
        if len(question_terms & answer_terms) < 2:
            reason_codes.append("QUESTION_MISMATCH")

        citation_matches = 0
        for citation_url in citation_urls:
            citation_text = self._fetch_url_text(citation_url)
            if len(keywords(citation_text) & answer_terms) > 0:
                citation_matches += 1
        if citation_urls and citation_matches == 0:
            reason_codes.append("UNSUPPORTED_CLAIMS")

        reason_codes = canonical_codes(reason_codes)
        accepted = len(reason_codes) == 0
        if accepted:
            reason_codes = ["PASS_MINIMUM_ACCEPTANCE"]
            summary = "Answer satisfies the SourceBounty acceptance rubric."
        else:
            summary = "Answer does not satisfy the SourceBounty acceptance rubric."

        evidence_digest = digest_payload(
            {"bountyId": bounty_id, "answer": canonical_text(answer_body), "citationUrls": sorted(citation_urls)}
        )
        verdict_digest = digest_payload(
            {"answerId": answer_id, "accepted": accepted, "reasonCodes": reason_codes}
        )
        return {
            "bountyId": bounty_id,
            "answerId": answer_id,
            "accepted": accepted,
            "summary": summary,
            "reasonCodes": reason_codes,
            "evidenceDigest": evidence_digest,
            "verdictDigest": verdict_digest,
        }

    def _parse_json_array(self, raw_json: str) -> list[str]:
        try:
            data = json.loads(raw_json or "[]")
        except Exception as exc:
            raise gl.vm.UserError(f"{ERROR_EXPECTED} Invalid JSON array") from exc
        if not isinstance(data, list):
            raise gl.vm.UserError(f"{ERROR_EXPECTED} Invalid JSON array")
        return [str(item) for item in data]

    def _fetch_url_text(self, url: str) -> str:
        try:
            return gl.get_webpage(url, mode="text")
        except Exception as exc:
            raise gl.vm.UserError(f"{ERROR_TRANSIENT} Unable to fetch webpage") from exc

    def _handle_leader_error(self, leaders_res: gl.vm.Result, leader_fn) -> bool:
        leader_msg = leaders_res.message if hasattr(leaders_res, "message") else ""
        try:
            leader_fn()
            return False
        except gl.vm.UserError as exc:
            validator_msg = exc.message if hasattr(exc, "message") else str(exc)
            if validator_msg.startswith(ERROR_EXPECTED):
                return validator_msg == leader_msg
            return validator_msg.startswith(ERROR_TRANSIENT) and leader_msg.startswith(ERROR_TRANSIENT)
        except Exception:
            return False
