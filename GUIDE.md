# Datafy — Step-by-Step Guide

A complete walkthrough: from a fresh machine, to running the app, to verifying a
CSV and downloading results, to switching on the real provider.

- **What it does:** upload a CSV of phone numbers or emails, check them against
  one or more services (WhatsApp, Telegram, Amazon, …) through checknumber.ai,
  and get results matched back to every original row.
- **Where it runs:** locally on your machine, at `http://127.0.0.1:8000`.
- **Provider:** ships with an offline **mock** (free, no key). Flip to the real
  **checknumber.ai** API when ready (Part 7).

---

## Table of contents

1. [Prerequisites](#1-prerequisites)
2. [One-time setup](#2-one-time-setup)
3. [Starting the app](#3-starting-the-app)
4. [The verification workflow (the main task)](#4-the-verification-workflow)
5. [Understanding the results](#5-understanding-the-results)
6. [The four downloads explained](#6-the-four-downloads)
7. [Switching to the real checknumber.ai provider](#7-switching-to-the-real-provider)
8. [Stopping & restarting](#8-stopping--restarting)
9. [Troubleshooting](#9-troubleshooting)
10. [How it works (reference)](#10-how-it-works-reference)

---

## 1. Prerequisites

- **Python 3.11+** (this project was built and tested on 3.13).
- A terminal.
- That's it — no database server, no Redis, no Node. It uses SQLite and
  server-rendered HTML.

Check your Python:

```bash
python3 --version
```

---

## 2. One-time setup

Do this once. From the project folder
(`.../claude-projects/datafy`):

```bash
# 1. Create an isolated environment
python3 -m venv .venv

# 2. Activate it  (you'll do this every new terminal — see the note below)
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Create the database tables
python manage.py migrate
```

> **The `source .venv/bin/activate` step** activates the virtual environment.
> You must run it in **every new terminal window** before using `python
> manage.py …`. You know it worked when your prompt shows `(.venv)`.

Optional — create an admin login for the Django admin panel
(`http://127.0.0.1:8000/admin/`), useful for inspecting raw data:

```bash
python manage.py createsuperuser
```

---

## 3. Starting the app

The app needs **two processes running at the same time**, so open **two
terminals** (activate the venv in each).

**Terminal 1 — the web server** (the thing you open in a browser):

```bash
source .venv/bin/activate
python manage.py runserver
```

Leave it running. It prints `Starting development server at
http://127.0.0.1:8000/`.

**Terminal 2 — the background worker** (does the actual verification):

```bash
source .venv/bin/activate
python manage.py run_worker
```

Leave it running too. It prints `Worker started. Ctrl-C to stop.`

> **Why two processes?** Verification is asynchronous — the worker submits
> batches to the provider, waits, fetches results, and advances each job through
> its steps. The web server just shows you pages. If the worker isn't running,
> jobs will sit at "Queued / Processing" and never finish.

Now open **http://127.0.0.1:8000** in your browser.

---

## 4. The verification workflow

This is the core task. Five stages, mirrored by the wizard.

### Step 1 — Start a new verification

1. Click **+ New Verification** (top-right).
2. Click **Choose file** and select your CSV.
3. Tick the authorization checkbox (you confirm you're allowed to process this
   data).
4. Click **Upload & continue**.

The file and every row are stored; nothing is changed.

### Step 2 — Prepare & configure

You'll see a **preview** of your data, then two panels.

**Left panel — Contact data:**

- **Data type:** *Phone number* or *Email address*. (This changes which
  services are offered on the right.)
- **Contact column:** the column that holds the numbers/emails.
- **Default country code** *(phone only):* a 2-letter code (e.g. `US`, `GB`,
  `BD`) applied to numbers that don't already start with `+`. Numbers that
  already include a `+country code` are left alone.
- **Country column** *(phone only, optional):* if your file has mixed countries
  and a column naming each row's country, pick it here.

**Right panel — Verification steps:**

- **Number of steps:** 1, 2, or 3.
- For each step, pick a **service** (WhatsApp, Telegram, …). Only services the
  chosen data type supports are shown.

Click **Continue to review**.

> **What happens here:** the app normalizes every contact (trims spaces, formats
> phones to E.164), flags anything missing or malformed, and de-duplicates —
> the same number appearing 5 times is verified **once**, but all 5 rows are
> kept and will get the result.

### Step 3 — Review & start

Check the summary:

- File, contact column, data type, country settings.
- **Total rows** vs **unique eligible contacts** (what will actually be checked).
- **Flagged** count (missing / malformed — these are skipped, not counted as
  invalid).
- The service order and the validity rule.

Click **Start verification**.

### Step 4 — Watch it process

You land on the **job detail page**. It updates live (no refresh needed):

- A status badge and a stage line (*Preparing → Verifying Step 1 → …*).
- A per-step table filling in **Checked / Valid / Invalid / Unresolved** counts.

**Multi-step filtering (important):** Step 2 only checks contacts that were
**valid** in Step 1; Step 3 only checks those valid in Step 2. A contact must
pass **every** selected step to end up valid. This is why later steps show
fewer "Checked" than earlier ones.

### Step 5 — Download results

When the status reads **Completed** (or **Partially completed**), the results
summary and **Downloads** section appear. See Part 6 for what each file is.

---

## 5. Understanding the results

Every checked contact lands in exactly one of three buckets:

| Bucket | Meaning |
|---|---|
| **Valid** | Passed the provider check (and passed *every* step, for multi-step jobs). |
| **Invalid** | The provider returned an explicit negative. |
| **Unresolved** | Unknown / timeout / provider error / not returned. **Never** treated as invalid — kept separate on purpose so you don't discard good contacts. |

Contacts that were **flagged** in preparation (missing or malformed) are not
checked at all and appear with their flag reason.

> **"Valid" means the contact passed the provider check.** It does **not**
> establish ownership of, consent from, or permission to contact that person.

---

## 6. The four downloads

| Button | Contents | Format |
|---|---|---|
| **Valid contacts** | Unique contacts that passed **all** selected steps, one per line. | `.txt` |
| **All results** | Every unique contact with its per-step status and final outcome. | `.txt`, tab-separated |
| **Complete valid database** | Only the original rows whose contact ended up valid, with all original columns **plus** verification fields. | `.csv` |
| **Complete database — all results** | **Every** original row (valid, invalid, unresolved, flagged), with verification fields. | `.csv` |

The two "Complete …" CSVs keep all your original columns and append:
`normalized_contact`, `stepN_service`, `stepN_result` (per step),
`final_outcome`, and `verification_date`. Duplicate rows are preserved.

---

## 7. Switching to the real provider

By default the app uses the **mock** provider — offline, free, deterministic —
so you can learn the workflow with no account. To verify against real accounts:

1. Get an API key from your checknumber.ai dashboard.
2. Stop the worker (Ctrl-C in Terminal 2).
3. Set two environment variables and restart it **in the same terminal**:

   ```bash
   export VERIFIER_PROVIDER=checknumber
   export CHECKNUMBER_API_KEY=your_key_here
   python manage.py run_worker
   ```

   (Do the same `export`s in the web-server terminal before `runserver` if you
   want cost estimates shown there too.)

> **Keep the key out of git.** Set it as an environment variable as above, or
> put it in a local `.env` you don't commit — never paste it into a source file.

### Two things to confirm once on the real API

Both are one-line edits, each in a single file, and both are commented in the
code:

1. **Which services truly support email.** `verifier/catalog.py` lists a
   provider `task_type` code for each (service × phone/email) combination,
   following checknumber's documented `_email` suffix pattern. Confirm against
   your account which services actually expose an email variant, and correct any
   that don't.
2. **The exact result labels.** `verifier/providers/checknumber.py` →
   `_map_status()` maps the provider's `activated` values (`yes` / `no` / …)
   onto valid / invalid / unresolved. Verify the labels your account returns.
   Anything unknown or missing already falls to **unresolved**, never invalid.

---

## 8. Stopping & restarting

- **Stop:** press **Ctrl-C** in each terminal (worker and server).
- **Restart later:** open two terminals and repeat [Part 3](#3-starting-the-app).
  You do **not** repeat the setup in Part 2 — that's one-time. Your past jobs and
  results are still in the database.

---

## 9. Troubleshooting

| Symptom | Cause & fix |
|---|---|
| Job stuck on "Queued" / "Processing" forever | The **worker isn't running**. Start Terminal 2: `python manage.py run_worker`. |
| `command not found: python` or wrong packages | The venv isn't active. Run `source .venv/bin/activate` (prompt should show `(.venv)`). |
| Browser can't reach the page | The **web server isn't running**, or you used a different port. Check Terminal 1; open the exact URL it prints. |
| "That file has no header row / columns" | Your CSV needs a header row (column names in the first line). |
| Job shows **Partially completed** | A step failed mid-way (e.g. provider error). Completed steps' results are kept; the reason is shown at the top of the job page. |
| Live provider errors immediately | `CHECKNUMBER_API_KEY` not set, or `VERIFIER_PROVIDER` still `mock`. Re-check the exports in Part 7. |
| Want to inspect raw data | Visit `http://127.0.0.1:8000/admin/` (needs the superuser from Part 2). |

---

## 10. How it works (reference)

```
verifier/
  catalog.py                 service × contact-type → provider task_type code
  models.py                  Job, Step, Contact (unique), SourceRow, StepResult
  providers/
    base.py                  the interface every provider implements
    mock.py                  offline, deterministic, free
    checknumber.py           real checknumber.ai adapter
  services/
    normalize.py             phone (E.164) / email normalization + flagging
    csv_utils.py             CSV read, preview, download builders
    orchestrator.py          prepare → step state machine → finalize + downloads
  management/commands/
    run_worker.py            the background process that advances jobs
  views.py                   dashboard, wizard, detail+progress, downloads, history
  templates/verifier/        the Bootstrap 5 pages
```

**The provider contract (checknumber.ai):** submit a file of contacts +
`task_type` to `POST /v1/tasks`; poll `POST /v1/gettasks` until `status ==
exported`; download the `result_url`; map `activated` to a bucket. It's async
and file-based, which is exactly why the worker exists.

**Guarantees the design enforces:**

- Original contact values are never mutated; the normalized form goes in its own
  column.
- Each unique contact is checked once; every original row is retained and matched
  back by its normalized value and internal row reference, preserving row order.
- Timeout / error / unknown is never classified as invalid.
- An interrupted job keeps its completed results and is marked *partially
  completed*.
