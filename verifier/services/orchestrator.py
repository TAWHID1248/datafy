"""Job orchestration: preparation, the step state machine, and downloads.

The worker calls ``advance_job`` repeatedly. Each call performs at most one
provider interaction (submit OR poll+fetch for one step) and returns a signal:

    CONTINUE  did work; call again right away
    WAIT      a step is submitted but the provider is not done; poll later
    DONE      job finished (completed / partial)
    FAILED    job failed

Sequential filtering (AND rule): step 1 checks all eligible contacts; step N>1
checks only contacts marked VALID at step N-1. Contacts that are INVALID or
UNRESOLVED drop out and are not checked further (unresolved is kept distinct
from invalid). Results are matched back to contacts by normalized value.
"""

from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from .. import catalog
from ..models import (
    Contact,
    JobStatus,
    JobStep,
    Outcome,
    SourceRow,
    StepResult,
    StepStatus,
    VerificationJob,
)
from ..providers import get_provider
from . import csv_utils
from .normalize import normalize

CONTINUE, WAIT, DONE, FAILED = "continue", "wait", "done", "failed"


# --------------------------------------------------------------------------- #
# Preparation
# --------------------------------------------------------------------------- #
def prepare_job(job: VerificationJob):
    """Parse the stored CSV, build source rows, normalize + dedup contacts."""
    with job.stored_file.open("rb") as fh:
        file_bytes = fh.read()
    columns, rows = csv_utils.read_csv(file_bytes)

    job.columns = columns
    job.total_rows = len(rows)
    job.save(update_fields=["columns", "total_rows"])

    # Clear any prior preparation (safe re-run).
    job.rows.all().delete()
    job.contacts.all().delete()

    by_norm: dict[str, Contact] = {}
    source_rows = []
    for idx, row in enumerate(rows):
        raw = row.get(job.contact_column, "")
        row_region = row.get(job.country_column) if job.country_column else None
        norm, reason = normalize(
            raw, job.contact_type,
            default_region=job.default_region or None,
            row_region=row_region,
        )
        contact = None
        if norm:
            contact = by_norm.get(norm)
            if contact is None:
                contact = Contact.objects.create(
                    job=job, raw_value=str(raw).strip(),
                    normalized=norm, is_eligible=True,
                )
                by_norm[norm] = contact
        else:
            # Ineligible values still become a Contact so the row keeps a link
            # and the flag is visible in the complete export. Deduped per reason.
            key = f"__flag__:{reason}:{str(raw).strip()}"
            contact = by_norm.get(key)
            if contact is None:
                contact = Contact.objects.create(
                    job=job, raw_value=str(raw).strip(),
                    normalized="", is_eligible=False, flag_reason=reason,
                )
                by_norm[key] = contact
        source_rows.append(
            SourceRow(job=job, row_index=idx, data=row, contact=contact)
        )
    SourceRow.objects.bulk_create(source_rows, batch_size=1000)


# --------------------------------------------------------------------------- #
# Step state machine
# --------------------------------------------------------------------------- #
def _contacts_for_step(job, step, prev_step):
    """Contacts eligible to be checked at this step."""
    if prev_step is None:
        return list(job.contacts.filter(is_eligible=True))
    valid_ids = StepResult.objects.filter(
        step=prev_step, outcome=Outcome.VALID
    ).values_list("contact_id", flat=True)
    return list(job.contacts.filter(id__in=list(valid_ids)))


def _advance_step(job, step, prev_step):
    provider = get_provider()
    contacts = _contacts_for_step(job, step, prev_step)
    values = [c.normalized for c in contacts]

    if step.status == StepStatus.PENDING:
        job.stage = f"Verifying Step {step.order}: {step.service_label}"
        job.save(update_fields=["stage"])
        if not values:
            # Nothing survived the previous filter; nothing to check.
            step.status = StepStatus.COMPLETED
            step.checked = 0
            step.completed_at = timezone.now()
            step.save()
            return CONTINUE
        sub = provider.submit(values, step.task_type)
        step.provider_task_id = sub.task_id
        step.status = StepStatus.SUBMITTED
        step.submitted_at = timezone.now()
        step.save()
        if sub.estimated_cost is not None:
            job.estimated_cost = (job.estimated_cost or Decimal(0)) + sub.estimated_cost
            job.save(update_fields=["estimated_cost"])
        return CONTINUE

    if step.status == StepStatus.SUBMITTED:
        poll = provider.poll(step.provider_task_id)
        if poll.failed:
            step.status = StepStatus.FAILED
            step.error = poll.message or "Provider reported task failure."
            step.save()
            return FAILED
        if not poll.done:
            return WAIT
        # Done: fetch and record per-contact outcomes.
        fetch = provider.fetch(poll, values)
        by_value = {s.value: s for s in fetch.statuses}
        counts = {Outcome.VALID: 0, Outcome.INVALID: 0, Outcome.UNRESOLVED: 0}
        results = []
        for c in contacts:
            st = by_value.get(c.normalized)
            outcome = st.outcome if st else Outcome.UNRESOLVED
            raw = st.raw_status if st else "missing"
            counts[outcome] = counts.get(outcome, 0) + 1
            results.append(StepResult(
                step=step, contact=c, outcome=outcome, raw_status=raw,
            ))
        with transaction.atomic():
            StepResult.objects.filter(step=step).delete()
            StepResult.objects.bulk_create(results, batch_size=1000)
        step.checked = len(contacts)
        step.valid = counts[Outcome.VALID]
        step.invalid = counts[Outcome.INVALID]
        step.unresolved = counts[Outcome.UNRESOLVED]
        step.status = StepStatus.COMPLETED
        step.completed_at = timezone.now()
        step.save()
        if fetch.actual_cost is not None:
            job.actual_cost = (job.actual_cost or Decimal(0)) + fetch.actual_cost
            job.save(update_fields=["actual_cost"])
        return CONTINUE

    return CONTINUE  # already completed


def advance_job(job: VerificationJob):
    """Perform one unit of work; return a CONTINUE/WAIT/DONE/FAILED signal."""
    if job.status in (JobStatus.COMPLETED, JobStatus.PARTIAL, JobStatus.FAILED):
        return DONE

    if job.status == JobStatus.QUEUED:
        job.status = JobStatus.PROCESSING
        job.stage = "Preparing"
        job.save(update_fields=["status", "stage"])
        if not job.contacts.exists():
            prepare_job(job)
        return CONTINUE

    steps = list(job.steps.all())
    prev = None
    for step in steps:
        if step.status == StepStatus.FAILED:
            return _finalize(job, failed_step=step)
        if step.status != StepStatus.COMPLETED:
            signal = _advance_step(job, step, prev)
            if signal == FAILED:
                return _finalize(job, failed_step=step)
            return signal
        prev = step

    # All steps completed.
    return _finalize(job)


def _finalize(job, failed_step=None):
    """Compute final per-contact outcomes and set the job's terminal status."""
    steps = list(job.steps.all())
    # Map (step_id, contact_id) -> outcome for eligible contacts.
    results = {
        (r.step_id, r.contact_id): r.outcome
        for r in StepResult.objects.filter(step__job=job)
    }
    for contact in job.contacts.filter(is_eligible=True):
        final = None
        for step in steps:
            outcome = results.get((step.id, contact.id))
            if outcome is None:
                break
            final = outcome
            if outcome != Outcome.VALID:
                break
        contact.final_outcome = final or Outcome.UNRESOLVED
        contact.save(update_fields=["final_outcome"])

    job.stage = "Completed"
    job.completed_at = timezone.now()
    if failed_step is not None:
        # Some steps ran; keep their results but mark the job incomplete.
        any_done = job.steps.filter(status=StepStatus.COMPLETED).exists()
        job.status = JobStatus.PARTIAL if any_done else JobStatus.FAILED
        job.error = f"Step {failed_step.order} failed: {failed_step.error}"
        job.stage = "Stopped (incomplete)"
    else:
        job.status = JobStatus.COMPLETED
    job.save()
    return FAILED if job.status == JobStatus.FAILED else DONE


# --------------------------------------------------------------------------- #
# Download builders
# --------------------------------------------------------------------------- #
def _final_valid_contacts(job):
    return list(
        job.contacts.filter(is_eligible=True, final_outcome=Outcome.VALID)
    )


def download_valid_txt(job):
    values = [c.normalized for c in _final_valid_contacts(job)]
    return csv_utils.build_valid_txt(values)


def download_all_results_txt(job):
    steps = list(job.steps.all())
    step_labels = [s.service_label for s in steps]
    results = {
        (r.step_id, r.contact_id): r.outcome
        for r in StepResult.objects.filter(step__job=job)
    }
    records = []
    for c in job.contacts.all():
        steps_map = {}
        for i, step in enumerate(steps, start=1):
            steps_map[i] = results.get((step.id, c.id), "skipped")
        records.append({
            "contact": c.raw_value,
            "normalized": c.normalized,
            "steps": steps_map,
            "final": c.final_outcome or (c.flag_reason or "flagged"),
        })
    return csv_utils.build_all_results_txt(records, step_labels)


def _appended_columns(job):
    cols = ["normalized_contact"]
    for i, step in enumerate(job.steps.all(), start=1):
        cols.append(f"step{i}_service")
        cols.append(f"step{i}_result")
    cols += ["final_outcome", "verification_date"]
    return cols


def _appended_for_contact(job, contact, steps, results):
    date = job.completed_at.isoformat() if job.completed_at else ""
    appended = {"normalized_contact": contact.normalized}
    for i, step in enumerate(steps, start=1):
        appended[f"step{i}_service"] = step.service_label
        appended[f"step{i}_result"] = results.get((step.id, contact.id), "skipped")
    appended["final_outcome"] = contact.final_outcome or (
        contact.flag_reason or "flagged"
    )
    appended["verification_date"] = date
    return appended


def download_complete_csv(job, valid_only=False):
    steps = list(job.steps.all())
    results = {
        (r.step_id, r.contact_id): r.outcome
        for r in StepResult.objects.filter(step__job=job)
    }
    appended_cols = _appended_columns(job)
    rows_with_results = []
    for src in job.rows.select_related("contact").all():
        contact = src.contact
        if valid_only and not (
            contact and contact.is_eligible
            and contact.final_outcome == Outcome.VALID
        ):
            continue
        appended = (
            _appended_for_contact(job, contact, steps, results)
            if contact else {}
        )
        rows_with_results.append((src.data, appended))
    return csv_utils.build_complete_csv(job.columns, rows_with_results, appended_cols)
