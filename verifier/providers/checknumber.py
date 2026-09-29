"""checknumber.ai adapter.

Implements the documented file-based async contract:

  POST  {base}/tasks     multipart: file=<one contact per line>, task_type=<code>
        -> {task_id, status, total, estimated_amount:{amount,currency}, ...}
  POST  {base}/gettasks  form: task_id=<id>
        -> {status: pending|processing|exported|failed, success, failure,
            result_url, actual_amount:{amount,currency}}
  GET   {base}/balance

Results are downloaded from ``result_url`` (a ZIP) and normally contain the
columns ``number`` (or ``phone`` / ``email`` / ``username``) and ``activated``.
The richer checkers (``ws_active``, ``ws_avatar``, ``tg_active``, ``tg_avatar``)
add more columns; those are ignored, only the verdict column drives the outcome.

A few checkers name their columns differently and are handled in ``_parse_row``:
``high_value_users`` exports ``Mobile Number`` / ``Result``; ``ws_business``
exports ``whatsapp`` / ``business`` (the business flag is the verdict); the
carrier lookups (``globalCarrier``, ``us_carrier_premium``) export no verdict at
all, only ``number_type`` / ``carrier`` / ... - a resolved carrier counts as
valid and the carrier text is kept as the raw status.

Status mapping (see the provider's own guidance: "treat only an explicit
determined result as a positive or negative classification; undetermined /
exists=false is not a negative"):

  activated == "yes"/"true"/"activated"      -> valid
  activated in {"no","bad","not_activated"}  -> invalid
  anything else, blank, or CONTACT MISSING   -> unresolved  (never invalid)

The exact set of ``activated`` values your account returns should be confirmed
against live results; the mapping is centralised in ``_map_status`` for that.
"""

import csv
import io
import zipfile
from decimal import Decimal, InvalidOperation

import requests
from django.conf import settings

from ..models import Outcome
from .base import (
    ContactStatus,
    FetchResult,
    PollResult,
    SubmitResult,
    VerificationProvider,
)

_VALID = {"yes", "true", "activated", "active", "1"}
_INVALID = {"no", "false", "not_activated", "bad", "inactive", "0"}

# Column that echoes the submitted contact, in lookup order.
_VALUE_KEYS = ("number", "phone", "mobile number", "email", "username")
# Column carrying the yes/no verdict, in lookup order.
_STATUS_KEYS = ("activated", "result", "business", "whatsapp")
# Columns that identify a carrier-lookup export (no verdict column).
_CARRIER_KEYS = ("carrier", "number_type", "underlying_carrier")
# Any of these in a header row marks the results table inside the export ZIP.
_TABLE_MARKERS = _STATUS_KEYS + _CARRIER_KEYS


def _match_key(value: str) -> str:
    """Join key for matching submitted contacts to result rows.

    The provider echoes phone numbers without the leading ``+`` (and may add
    other formatting), so compare digits only. Emails and usernames compare
    case-insensitively, ignoring a leading ``@``.
    """
    v = (value or "").strip().lstrip("@").strip()
    if "@" in v or any(ch.isalpha() for ch in v):
        return v.lower()
    digits = "".join(ch for ch in v if ch.isdigit())
    return digits or v


def _parse_row(norm: dict) -> tuple[str, str]:
    """Map one lower-cased result row to (outcome, raw_status)."""
    for key in _STATUS_KEYS:
        if key in norm:
            raw = norm[key].strip()
            return _map_status(raw), raw
    if any(key in norm for key in _CARRIER_KEYS):
        parts = [norm.get("number_type", "").strip(), norm.get("carrier", "").strip()]
        detail = " · ".join(part for part in parts if part)
        if detail:
            return Outcome.VALID, detail
        return Outcome.UNRESOLVED, "no carrier"
    return Outcome.UNRESOLVED, ""


def _map_status(raw: str) -> str:
    key = (raw or "").strip().lower()
    if key in _VALID:
        return Outcome.VALID
    if key in _INVALID:
        return Outcome.INVALID
    return Outcome.UNRESOLVED


def _amount(obj) -> Decimal | None:
    if not isinstance(obj, dict):
        return None
    try:
        return Decimal(str(obj.get("amount")))
    except (InvalidOperation, TypeError):
        return None


def _check(resp):
    """Raise a readable error carrying the provider's own message, if any."""
    if resp.ok:
        return
    detail = ""
    try:
        body = resp.json()
        detail = body.get("message") or body.get("error") or ""
    except ValueError:
        detail = resp.text[:200]
    raise RuntimeError(f"checknumber.ai {resp.status_code}: {detail}".strip())


class CheckNumberProvider(VerificationProvider):
    name = "checknumber"

    def __init__(self):
        self.base = settings.CHECKNUMBER_BASE_URL.rstrip("/")
        self.api_key = settings.CHECKNUMBER_API_KEY
        if not self.api_key:
            raise RuntimeError(
                "CHECKNUMBER_API_KEY is not set; cannot use the live provider."
            )

    @property
    def _headers(self):
        return {"X-API-Key": self.api_key}

    def submit(self, contacts, task_type):
        contacts = list(contacts)
        payload = ("\n".join(contacts)).encode("utf-8")
        files = {"file": ("contacts.txt", payload, "text/plain")}
        data = {"task_type": task_type}
        resp = requests.post(
            f"{self.base}/tasks", headers=self._headers,
            files=files, data=data, timeout=60,
        )
        _check(resp)
        body = resp.json()
        return SubmitResult(
            task_id=str(body["task_id"]),
            total=int(body.get("total", len(contacts))),
            estimated_cost=_amount(body.get("estimated_amount")),
        )

    def poll(self, task_id):
        resp = requests.post(
            f"{self.base}/gettasks", headers=self._headers,
            data={"task_id": task_id}, timeout=60,
        )
        _check(resp)
        body = resp.json()
        state = str(body.get("status", "")).lower()
        return PollResult(
            state=state,
            done=(state == "exported"),
            failed=(state == "failed"),
            checked=int(body.get("success", 0)),
            result_url=body.get("result_url", "") or "",
            actual_cost=_amount(body.get("actual_amount")),
            message=body.get("message", "") or "",
        )

    def fetch(self, poll_result, contacts):
        rows = self._download_rows(poll_result.result_url)
        found = {}
        for row in rows:
            # Richer checkers return extra columns and may capitalise headers
            # (Telegram profile exports "Phone"), so look up case-insensitively.
            norm = {(k or "").strip().lower(): (v or "") for k, v in row.items()}
            value = ""
            for key in _VALUE_KEYS:
                value = (norm.get(key) or "").strip()
                if value:
                    break
            if value:
                found[_match_key(value)] = _parse_row(norm)
        statuses = []
        for c in contacts:
            key = _match_key(c)
            if key in found:
                outcome, raw = found[key]
                statuses.append(
                    ContactStatus(value=c, outcome=outcome, raw_status=raw)
                )
            else:
                # Submitted but absent from results -> unchecked, not invalid.
                statuses.append(
                    ContactStatus(
                        value=c, outcome=Outcome.UNRESOLVED, raw_status="missing"
                    )
                )
        return FetchResult(statuses=statuses, actual_cost=poll_result.actual_cost)

    def _download_rows(self, result_url):
        resp = requests.get(result_url, headers=self._headers, timeout=120)
        resp.raise_for_status()
        content = resp.content
        # result_url points at a ZIP; fall back to raw text if it is not zipped.
        try:
            zf = zipfile.ZipFile(io.BytesIO(content))
            text = self._pick_member(zf)
        except zipfile.BadZipFile:
            text = content.decode("utf-8", errors="replace")
        sample = text[:4096]
        delimiter = "\t" if sample.count("\t") > sample.count(",") else ","
        return list(csv.DictReader(io.StringIO(text), delimiter=delimiter))

    @staticmethod
    def _pick_member(zf):
        """Choose the results table from the export ZIP.

        The export contains several files (``registered.txt``,
        ``unregistered.txt``, ``all.csv``, ``result.xlsx``); only ``all.csv``
        carries the full ``number,activated`` table, so prefer the member whose
        header row mentions a verdict or carrier column, then any ``.csv``,
        then the first file at all.
        """
        csv_fallback = None
        first = None
        for name in zf.namelist():
            if name.endswith("/"):
                continue
            text = zf.read(name).decode("utf-8", errors="replace")
            if first is None:
                first = text
            header = text.split("\n", 1)[0].lower()
            if any(marker in header for marker in _TABLE_MARKERS):
                return text
            if csv_fallback is None and name.lower().endswith(".csv"):
                csv_fallback = text
        return csv_fallback if csv_fallback is not None else (first or "")

    def balance(self):
        try:
            resp = requests.get(
                f"{self.base}/balance", headers=self._headers, timeout=30
            )
            resp.raise_for_status()
            body = resp.json()
            # Balance may be {"balance": 20.08}, a bare number, or {"amount": ..}.
            raw = body.get("balance") if isinstance(body, dict) else body
            if isinstance(raw, dict):
                return _amount(raw)
            try:
                return Decimal(str(raw))
            except (InvalidOperation, TypeError):
                return _amount(body)
        except requests.RequestException:
            return None
