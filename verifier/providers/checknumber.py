"""checknumber.ai adapter.

Implements the documented file-based async contract:

  POST  {base}/tasks     multipart: file=<one contact per line>, task_type=<code>
        -> {task_id, status, total, estimated_amount:{amount,currency}, ...}
  POST  {base}/gettasks  form: task_id=<id>
        -> {status: pending|processing|exported|failed, success, failure,
            result_url, actual_amount:{amount,currency}}
  GET   {base}/balance

Results are downloaded from ``result_url`` (a ZIP) and contain two columns:
``number`` (or ``email``) and ``activated``.

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
        resp.raise_for_status()
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
        resp.raise_for_status()
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
            value = (row.get("number") or row.get("email") or "").strip()
            if value:
                found[value] = _map_status(row.get("activated", ""))
        statuses = []
        for c in contacts:
            if c in found:
                statuses.append(
                    ContactStatus(value=c, outcome=found[c], raw_status=found[c])
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
            name = zf.namelist()[0]
            text = zf.read(name).decode("utf-8", errors="replace")
        except zipfile.BadZipFile:
            text = content.decode("utf-8", errors="replace")
        sample = text[:4096]
        delimiter = "\t" if sample.count("\t") > sample.count(",") else ","
        return list(csv.DictReader(io.StringIO(text), delimiter=delimiter))

    def balance(self):
        try:
            resp = requests.get(
                f"{self.base}/balance", headers=self._headers, timeout=30
            )
            resp.raise_for_status()
            body = resp.json()
            return _amount(body) or _amount(body.get("balance"))
        except requests.RequestException:
            return None
