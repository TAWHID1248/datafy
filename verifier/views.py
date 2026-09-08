"""Views: dashboard, the upload -> configure -> review -> process wizard,
job detail with live progress, downloads, and history."""

import json

from django.contrib import messages
from django.core.files.base import ContentFile
from django.db.models import Count, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from . import catalog, regions, samples
from .models import (
    ContactType,
    JobStatus,
    JobStep,
    Outcome,
    StepResult,
    VerificationJob,
)
from .providers import get_provider
from .services import csv_utils, orchestrator


# --------------------------------------------------------------------------- #
# Dashboard
# --------------------------------------------------------------------------- #
def dashboard(request):
    jobs = VerificationJob.objects.exclude(status=JobStatus.DRAFT)
    totals = {"valid": 0, "invalid": 0, "unresolved": 0}
    for job in jobs:
        if job.status in (JobStatus.COMPLETED, JobStatus.PARTIAL):
            c = job.final_counts()
            for k in totals:
                totals[k] += c[k]
    context = {
        "nav": "dashboard",
        "total_files": jobs.count(),
        "total_contacts": sum(j.eligible_contacts for j in jobs),
        "totals": totals,
        "running": jobs.filter(
            status__in=[JobStatus.QUEUED, JobStatus.PROCESSING]
        ),
        "recent": jobs[:8],
        "balance": _provider_balance(),
    }
    return render(request, "verifier/dashboard.html", context)


def _provider_balance():
    """Best-effort remaining provider credit; None if unavailable."""
    try:
        return get_provider().balance()
    except Exception:  # noqa: BLE001 - dashboard must never fail on this
        return None


# --------------------------------------------------------------------------- #
# Wizard
# --------------------------------------------------------------------------- #
def verification_start(request):
    if request.method == "POST":
        upload = request.FILES.get("file")
        if not upload:
            messages.error(request, "Please choose a CSV file to upload.")
            return redirect("verifier:start")
        file_bytes = upload.read()
        try:
            columns, rows = csv_utils.read_csv(file_bytes)
        except Exception as exc:  # noqa: BLE001
            messages.error(request, f"Could not read that CSV: {exc}")
            return redirect("verifier:start")
        if not columns:
            messages.error(request, "That file has no header row / columns.")
            return redirect("verifier:start")

        job = VerificationJob.objects.create(
            file_name=upload.name,
            contact_type=ContactType.PHONE,
            columns=columns,
            total_rows=len(rows),
            status=JobStatus.DRAFT,
        )
        # Re-wrap the already-read bytes so the FileField stores it.
        job.stored_file.save(upload.name, ContentFile(file_bytes), save=True)
        return redirect("verifier:configure", pk=job.pk)

    return render(request, "verifier/start.html", {"nav": "verification"})


def _preview(job, limit=8):
    with job.stored_file.open("rb") as fh:
        columns, rows = csv_utils.read_csv(fh.read())
    return columns, rows[:limit]


def job_configure(request, pk):
    job = get_object_or_404(VerificationJob, pk=pk)
    columns, preview_rows = _preview(job)

    if request.method == "POST":
        job.contact_type = request.POST.get("contact_type", ContactType.PHONE)
        job.contact_column = request.POST.get("contact_column", "")
        job.default_region = request.POST.get("default_region", "").strip().upper()
        job.country_column = request.POST.get("country_column", "")
        job.combine_rule = "all"

        if not job.contact_column:
            messages.error(request, "Select the column that holds the contacts.")
            return redirect("verifier:configure", pk=job.pk)

        # Build the ordered steps from the submitted services.
        num_steps = int(request.POST.get("num_steps", "1"))
        job.steps.all().delete()
        chosen = []
        for i in range(1, num_steps + 1):
            svc = request.POST.get(f"service_{i}", "").strip()
            if not svc:
                continue
            checker = (
                request.POST.get(f"checker_{i}", "").strip()
                or catalog.DEFAULT_CHECKER
            )
            task_type = catalog.task_type_for(svc, job.contact_type, checker)
            if not task_type:
                messages.error(
                    request,
                    f"{catalog.label_for(svc)} does not support "
                    f"{job.get_contact_type_display().lower()} checks "
                    f"with the selected checker.",
                )
                return redirect("verifier:configure", pk=job.pk)
            chosen.append((svc, checker, task_type))
        if not chosen:
            messages.error(request, "Choose at least one verification service.")
            return redirect("verifier:configure", pk=job.pk)

        job.save()
        for order, (svc, checker, task_type) in enumerate(chosen, start=1):
            JobStep.objects.create(
                job=job, order=order, service_key=svc,
                service_label=catalog.label_for(svc), task_type=task_type,
                checker=checker,
                checker_label=catalog.checker_label_for(
                    svc, job.contact_type, checker
                ),
            )
        # Normalize + dedup now so the review page can show real counts.
        orchestrator.prepare_job(job)
        return redirect("verifier:review", pk=job.pk)

    popular_regions, other_regions = regions.region_choices()
    context = {
        "nav": "verification",
        "job": job,
        "columns": columns,
        "preview_rows": preview_rows,
        "phone_services": catalog.services_for(catalog.PHONE),
        "email_services": catalog.services_for(catalog.EMAIL),
        "checkers_json": json.dumps({
            ct: {
                key: [
                    {"key": ck, "label": cl, "price": cp}
                    for ck, cl, cp, _tt in catalog.checkers_for(key, ct)
                ]
                for key, _label, _tt in catalog.services_for(ct)
            }
            for ct in (catalog.PHONE, catalog.EMAIL)
        }),
        "contact_types": ContactType.choices,
        "popular_regions": popular_regions,
        "other_regions": other_regions,
    }
    return render(request, "verifier/configure.html", context)


def job_review(request, pk):
    job = get_object_or_404(VerificationJob, pk=pk)
    if request.method == "POST":
        job.status = JobStatus.QUEUED
        job.stage = "Queued"
        job.save(update_fields=["status", "stage"])
        messages.success(request, "Verification started.")
        return redirect("verifier:detail", pk=job.pk)

    flagged = job.contacts.filter(is_eligible=False)
    flag_summary = flagged.values("flag_reason").annotate(n=Count("id"))
    context = {
        "nav": "verification",
        "job": job,
        "steps": job.steps.all(),
        "flag_summary": flag_summary,
    }
    return render(request, "verifier/review.html", context)


# --------------------------------------------------------------------------- #
# Detail + progress
# --------------------------------------------------------------------------- #
def job_detail(request, pk):
    job = get_object_or_404(VerificationJob, pk=pk)
    context = {
        "nav": "history",
        "job": job,
        "steps": job.steps.all(),
        "counts": (
            job.final_counts()
            if job.status in (JobStatus.COMPLETED, JobStatus.PARTIAL)
            else None
        ),
        "is_active": job.status in (JobStatus.QUEUED, JobStatus.PROCESSING),
    }
    return render(request, "verifier/detail.html", context)


def job_status(request, pk):
    """JSON used by the detail page to poll live progress."""
    job = get_object_or_404(VerificationJob, pk=pk)
    steps = [
        {
            "order": s.order,
            "label": s.display_label,
            "status": s.get_status_display(),
            "checked": s.checked,
            "valid": s.valid,
            "invalid": s.invalid,
            "unresolved": s.unresolved,
        }
        for s in job.steps.all()
    ]
    active = job.status in (JobStatus.QUEUED, JobStatus.PROCESSING)
    return JsonResponse({
        "status": job.status,
        "status_display": job.get_status_display(),
        "stage": job.stage,
        "active": active,
        "steps": steps,
        "counts": (
            job.final_counts()
            if job.status in (JobStatus.COMPLETED, JobStatus.PARTIAL)
            else None
        ),
        "estimated_cost": str(job.estimated_cost) if job.estimated_cost else None,
        "actual_cost": str(job.actual_cost) if job.actual_cost else None,
    })


# --------------------------------------------------------------------------- #
# Downloads
# --------------------------------------------------------------------------- #
def _txt(content, filename):
    resp = HttpResponse(content, content_type="text/plain; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp


def _csv(content, filename):
    resp = HttpResponse(content, content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp


def job_download(request, pk, kind):
    job = get_object_or_404(VerificationJob, pk=pk)
    base = job.file_name.rsplit(".", 1)[0]
    if kind == "valid":
        return _txt(orchestrator.download_valid_txt(job), f"{base}_valid.txt")
    if kind == "all":
        return _txt(
            orchestrator.download_all_results_txt(job), f"{base}_all_results.txt"
        )
    if kind == "complete_valid":
        return _csv(
            orchestrator.download_complete_csv(job, valid_only=True),
            f"{base}_valid_database.csv",
        )
    if kind == "complete_all":
        return _csv(
            orchestrator.download_complete_csv(job, valid_only=False),
            f"{base}_complete_database.csv",
        )
    return redirect("verifier:detail", pk=job.pk)


def step_download(request, pk, order):
    """Download the contacts checked at one step (per-service export)."""
    job = get_object_or_404(VerificationJob, pk=pk)
    step = get_object_or_404(JobStep, job=job, order=order)
    base = job.file_name.rsplit(".", 1)[0]
    slug = step.display_label.lower().replace(" · ", "_").replace(" ", "_")
    valid_only = request.GET.get("valid") == "1"
    suffix = "valid" if valid_only else "checked"
    return _txt(
        orchestrator.download_step_txt(job, step, valid_only=valid_only),
        f"{base}_{slug}_{suffix}.txt",
    )


# --------------------------------------------------------------------------- #
# History
# --------------------------------------------------------------------------- #
def history(request):
    q = request.GET.get("q", "").strip()
    jobs = VerificationJob.objects.exclude(status=JobStatus.DRAFT)
    if q:
        jobs = jobs.filter(
            Q(file_name__icontains=q) | Q(steps__service_label__icontains=q)
        ).distinct()
    return render(request, "verifier/history.html",
                  {"nav": "history", "jobs": jobs, "q": q})


# --------------------------------------------------------------------------- #
# Sample data, deletion, retention
# --------------------------------------------------------------------------- #
def use_sample(request):
    """Create a job from the bundled sample CSV and jump into configuration."""
    columns, rows = csv_utils.read_csv(samples.SAMPLE_CSV.encode("utf-8"))
    job = VerificationJob.objects.create(
        file_name=samples.SAMPLE_FILENAME,
        contact_type=ContactType.PHONE,
        columns=columns,
        total_rows=len(rows),
        status=JobStatus.DRAFT,
    )
    job.stored_file.save(
        samples.SAMPLE_FILENAME,
        ContentFile(samples.SAMPLE_CSV.encode("utf-8")),
        save=True,
    )
    messages.success(request, "Loaded a sample CSV — configure and run it.")
    return redirect("verifier:configure", pk=job.pk)


@require_POST
def delete_job(request, pk):
    job = get_object_or_404(VerificationJob, pk=pk)
    name = job.file_name
    if job.stored_file:
        job.stored_file.delete(save=False)
    job.delete()
    messages.success(request, f"Deleted “{name}” and its results.")
    return redirect("verifier:history")


@require_POST
def clear_history(request):
    """Delete all finished jobs (retention/cleanup). Running jobs are kept."""
    jobs = VerificationJob.objects.exclude(
        status__in=[JobStatus.QUEUED, JobStatus.PROCESSING]
    )
    n = 0
    for job in jobs:
        if job.stored_file:
            job.stored_file.delete(save=False)
        job.delete()
        n += 1
    messages.success(request, f"Cleared {n} job{'' if n == 1 else 's'} from history.")
    return redirect("verifier:history")
