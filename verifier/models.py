"""Data model for the verification system.

Design notes
------------
* A ``VerificationJob`` owns the uploaded file, the chosen contact column, and
  1-3 ordered ``JobStep`` rows (one per verification service).
* Contacts are de-duplicated: each unique normalized value becomes one
  ``Contact`` row. Every original CSV row maps to a ``Contact`` via
  ``SourceRow`` (keeping row order and the internal reference), so one checked
  contact can fan back out to many original rows.
* Per-step outcomes live on ``StepResult`` (one per contact per step). The
  three-bucket outcome (valid / invalid / unresolved) is an enum so a timeout
  or provider error is never silently treated as invalid.
"""

from django.db import models


class Outcome(models.TextChoices):
    """Normalized per-contact result buckets."""

    VALID = "valid", "Valid"
    INVALID = "invalid", "Invalid"
    UNRESOLVED = "unresolved", "Unresolved"  # unknown / error / timeout
    SKIPPED = "skipped", "Skipped"           # filtered out before this step ran


class JobStatus(models.TextChoices):
    DRAFT = "draft", "Draft"                       # wizard not yet started
    QUEUED = "queued", "Queued"
    PROCESSING = "processing", "Processing"
    COMPLETED = "completed", "Completed"
    PARTIAL = "partial", "Partially completed"
    FAILED = "failed", "Failed"


class StepStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    SUBMITTED = "submitted", "Submitted"     # sent to provider, awaiting results
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"


class ContactType(models.TextChoices):
    PHONE = "phone", "Phone number"
    EMAIL = "email", "Email address"


class VerificationJob(models.Model):
    file_name = models.CharField(max_length=255)
    stored_file = models.FileField(upload_to="uploads/")
    contact_type = models.CharField(max_length=10, choices=ContactType.choices)
    contact_column = models.CharField(max_length=255, blank=True)
    default_region = models.CharField(max_length=2, blank=True)  # ISO country
    country_column = models.CharField(max_length=255, blank=True)

    columns = models.JSONField(default=list)     # original header, in order
    total_rows = models.IntegerField(default=0)

    # combine rule for multi-step validity. "all" = pass every step (AND).
    combine_rule = models.CharField(max_length=10, default="all")

    status = models.CharField(
        max_length=20, choices=JobStatus.choices, default=JobStatus.DRAFT
    )
    stage = models.CharField(max_length=60, blank=True)  # human-readable progress
    error = models.TextField(blank=True)

    estimated_cost = models.DecimalField(
        max_digits=12, decimal_places=6, null=True, blank=True
    )
    actual_cost = models.DecimalField(
        max_digits=12, decimal_places=6, null=True, blank=True
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.file_name} ({self.get_status_display()})"

    @property
    def unique_contacts(self):
        return self.contacts.count()

    @property
    def eligible_contacts(self):
        return self.contacts.filter(is_eligible=True).count()

    @property
    def flagged_contacts(self):
        return self.contacts.filter(is_eligible=False).count()

    @property
    def service_order(self):
        return " → ".join(s.service_label for s in self.steps.all())

    def final_counts(self):
        """Return {valid, invalid, unresolved} over eligible contacts."""
        from django.db.models import Count

        rows = self.contacts.filter(is_eligible=True).values(
            "final_outcome"
        ).annotate(n=Count("id"))
        counts = {"valid": 0, "invalid": 0, "unresolved": 0}
        for r in rows:
            key = r["final_outcome"] or "unresolved"
            if key in counts:
                counts[key] += r["n"]
            elif key == Outcome.SKIPPED:
                counts["invalid"] += r["n"]
        return counts


class JobStep(models.Model):
    """One verification service applied at a position in the pipeline."""

    job = models.ForeignKey(
        VerificationJob, related_name="steps", on_delete=models.CASCADE
    )
    order = models.PositiveSmallIntegerField()   # 1, 2, or 3
    service_key = models.CharField(max_length=40)
    service_label = models.CharField(max_length=60)
    task_type = models.CharField(max_length=60)  # provider code, e.g. amazon_email

    status = models.CharField(
        max_length=20, choices=StepStatus.choices, default=StepStatus.PENDING
    )
    provider_task_id = models.CharField(max_length=120, blank=True)
    error = models.TextField(blank=True)

    checked = models.IntegerField(default=0)
    valid = models.IntegerField(default=0)
    invalid = models.IntegerField(default=0)
    unresolved = models.IntegerField(default=0)

    submitted_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["order"]
        unique_together = [("job", "order")]

    def __str__(self):
        return f"Step {self.order}: {self.service_label}"


class Contact(models.Model):
    """A unique normalized contact within a job (checked at most once per step)."""

    job = models.ForeignKey(
        VerificationJob, related_name="contacts", on_delete=models.CASCADE
    )
    raw_value = models.CharField(max_length=320)        # representative original
    normalized = models.CharField(max_length=320, blank=True)
    is_eligible = models.BooleanField(default=True)     # False = missing/malformed
    flag_reason = models.CharField(max_length=120, blank=True)

    final_outcome = models.CharField(
        max_length=12, choices=Outcome.choices, blank=True
    )

    class Meta:
        indexes = [models.Index(fields=["job", "normalized"])]

    def __str__(self):
        return self.normalized or self.raw_value


class SourceRow(models.Model):
    """One original CSV row, preserving order and its link to a Contact."""

    job = models.ForeignKey(
        VerificationJob, related_name="rows", on_delete=models.CASCADE
    )
    row_index = models.IntegerField()          # internal reference, 0-based
    data = models.JSONField()                  # original row as {column: value}
    contact = models.ForeignKey(
        Contact, related_name="source_rows", null=True,
        on_delete=models.SET_NULL,
    )

    class Meta:
        ordering = ["row_index"]
        indexes = [models.Index(fields=["job", "row_index"])]


class StepResult(models.Model):
    """Outcome of one contact at one step."""

    step = models.ForeignKey(
        JobStep, related_name="results", on_delete=models.CASCADE
    )
    contact = models.ForeignKey(
        Contact, related_name="step_results", on_delete=models.CASCADE
    )
    outcome = models.CharField(max_length=12, choices=Outcome.choices)
    raw_status = models.CharField(max_length=60, blank=True)  # provider's label

    class Meta:
        unique_together = [("step", "contact")]
        indexes = [models.Index(fields=["step", "outcome"])]
