# Datafy — Database Verification System

Internal tool: upload a CSV of phone numbers, emails, or usernames, verify them
through one or more services (WhatsApp, Telegram, Amazon, Gmail, Binance, … the
full checknumber.ai catalog: 52 services, 91 checker tiers) and get the results
matched back to every original row.

## Stack

- **Django 6** + **Bootstrap 5** (server-rendered wizard, no build step)
- **stdlib csv** + **phonenumbers** (Google libphonenumber) for parsing/normalizing
- Verification runs **asynchronously** via a lightweight worker command — no
  Celery/Redis needed. The provider (checknumber.ai) is itself async
  (submit → poll → download), so one polling loop is enough.

## Run it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate

# Terminal 1 — web server
python manage.py runserver

# Terminal 2 — background worker (advances jobs)
python manage.py run_worker
```

Open http://127.0.0.1:8000/ . By default it uses the **mock provider** — no API
key, no cost, deterministic results — so the whole flow works offline.

## Going live with checknumber.ai

Set two environment variables and restart the worker:

```bash
export VERIFIER_PROVIDER=checknumber
export CHECKNUMBER_API_KEY=your_key_here
```

The adapter (`verifier/providers/checknumber.py`) implements the documented
contract: `POST /v1/tasks` (multipart file + `task_type`), poll `POST
/v1/gettasks` until `status == exported`, download the `result_url` ZIP, and map
`activated` → valid/invalid/unresolved.

### Two things to confirm against your live account

1. **Per-service variants.** `verifier/catalog.py` lists the `task_type`
   code for each (service × phone/email/username) combo from the checknumber
   docs. Two dashboard-only tiers have no public docs and are marked
   `UNCONFIRMED` in the catalog (X Profile Checker → `twitter_profile`, PayPal
   Number Checker → `paypal`); a wrong code fails the step at submit time with
   the provider's message and costs nothing. Correct the catalog (one line each).
2. **`activated` values.** `checknumber.py::_map_status` maps `yes/no/...` onto
   the three buckets. Verify the exact labels your account returns. Anything
   undetermined or missing is treated as **unresolved**, never invalid.

## Architecture

```
verifier/
  catalog.py                 service × contact-type → provider task_type
  models.py                  Job, Step, Contact (unique), SourceRow, StepResult
  providers/                 base interface + mock + checknumber adapter
  services/
    normalize.py             phone (E.164) / email normalization + flagging
    csv_utils.py             CSV read, preview, download builders
    orchestrator.py          prepare → step state machine → finalize + downloads
  management/commands/
    run_worker.py            drives queued/processing jobs to completion
  views.py                   dashboard, wizard, detail+progress, downloads, history
```

Contact types: **phone** (E.164 via libphonenumber), **email**, and
**username** (Telegram handles / LinkedIn slugs; `@` and profile URLs are
stripped). Carrier lookups (Number Carrier, US Carrier Advanced) return carrier
data instead of yes/no: a resolved carrier counts as *valid* and the carrier
text lands in the `detail` column of the per-step and complete exports.

Key guarantees: original values are never mutated (normalized form goes in its
own column); duplicate contacts are checked once but every original row is kept
and matched back by normalized value; timeout/error/unknown is never classified
as invalid; an interrupted job is retained and marked *partially completed*.
