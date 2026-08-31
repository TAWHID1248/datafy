"""Tests for the verification pipeline and views (mock provider)."""

import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from . import catalog
from .models import (
    Contact,
    ContactType,
    JobStatus,
    JobStep,
    Outcome,
    SourceRow,
    StepStatus,
    VerificationJob,
)
from .services import orchestrator
from .services.normalize import normalize_email, normalize_phone

SAMPLE = (
    "name,phone,notes\n"
    "Alice,+14155552671,vip\n"
    "Bob,4155552672,\n"                    # bare -> needs US region
    "Carol,+8613800138000,cn\n"
    "Dave,4155552671,dup\n"                # national dup of Alice
    "Eve,not-a-number,bad\n"
    "Frank,,missing\n"
    "Grace,+442071838750,uk\n"
)

_MEDIA = tempfile.mkdtemp()


class NormalizeTests(TestCase):
    def test_bare_number_uses_default_region(self):
        val, reason = normalize_phone("4155552672", default_region="US")
        self.assertEqual(val, "+14155552672")
        self.assertEqual(reason, "")

    def test_international_prefix_preserved(self):
        val, reason = normalize_phone("+8613800138000", default_region="US")
        self.assertEqual(val, "+8613800138000")
        self.assertEqual(reason, "")

    def test_spaces_and_formatting_stripped(self):
        val, _ = normalize_phone("+44 20 7183 8750", default_region="US")
        self.assertEqual(val, "+442071838750")

    def test_missing_and_malformed_flagged(self):
        self.assertEqual(normalize_phone("", default_region="US")[1], "missing")
        self.assertEqual(normalize_phone("not-a-number", default_region="US")[1], "no digits")

    def test_bare_number_without_region_flagged(self):
        val, reason = normalize_phone("5552671", default_region=None)
        self.assertEqual(val, "")
        self.assertEqual(reason, "no country code")

    def test_email_normalization(self):
        self.assertEqual(normalize_email("  Foo@Bar.COM ")[0], "foo@bar.com")
        self.assertEqual(normalize_email("nope")[1], "malformed email")


@override_settings(MEDIA_ROOT=_MEDIA, VERIFIER_PROVIDER="mock")
class PipelineTests(TestCase):
    def _make_job(self, steps=("whatsapp", "telegram")):
        job = VerificationJob.objects.create(
            file_name="contacts.csv", contact_type=ContactType.PHONE,
            contact_column="phone", default_region="US",
            status=JobStatus.QUEUED,
        )
        job.stored_file.save("contacts.csv", SimpleUploadedFile("c.csv", SAMPLE.encode()))
        for i, key in enumerate(steps, start=1):
            JobStep.objects.create(
                job=job, order=i, service_key=key,
                service_label=catalog.label_for(key),
                task_type=catalog.task_type_for(key, "phone"),
            )
        return job

    def _run(self, job):
        for _ in range(50):
            sig = orchestrator.advance_job(job)
            job.refresh_from_db()
            if sig in (orchestrator.DONE, orchestrator.FAILED):
                break
        return job

    def test_prepare_dedup_and_flagging(self):
        job = self._make_job()
        orchestrator.prepare_job(job)
        # 7 rows, Alice+Dave dedup to 1 -> 4 eligible + 2 flagged = 6 unique.
        self.assertEqual(SourceRow.objects.filter(job=job).count(), 7)
        self.assertEqual(job.eligible_contacts, 4)
        self.assertEqual(job.flagged_contacts, 2)

    def test_full_run_sequential_filtering(self):
        job = self._run(self._make_job())
        self.assertEqual(job.status, JobStatus.COMPLETED)
        s1, s2 = job.steps.all()
        # Step 2 checks only what passed step 1.
        self.assertEqual(s2.checked, s1.valid)
        self.assertTrue(all(s.status == StepStatus.COMPLETED for s in (s1, s2)))

    def test_unresolved_never_counted_as_invalid(self):
        job = self._run(self._make_job())
        counts = job.final_counts()
        total = counts["valid"] + counts["invalid"] + counts["unresolved"]
        self.assertEqual(total, job.eligible_contacts)
        # buckets are disjoint and unresolved is its own bucket
        self.assertGreaterEqual(counts["unresolved"], 0)

    def test_downloads_preserve_all_rows_and_columns(self):
        job = self._run(self._make_job())
        complete = orchestrator.download_complete_csv(job, valid_only=False)
        lines = complete.strip().splitlines()
        # header + 7 original rows retained (duplicates kept)
        self.assertEqual(len(lines), 8)
        self.assertIn("name,phone,notes", lines[0])
        self.assertIn("normalized_contact", lines[0])
        self.assertIn("final_outcome", lines[0])

    def test_valid_txt_only_final_valid(self):
        job = self._run(self._make_job())
        txt = orchestrator.download_valid_txt(job)
        valid_contacts = job.contacts.filter(
            is_eligible=True, final_outcome=Outcome.VALID
        )
        expected = {c.normalized for c in valid_contacts}
        got = {l for l in txt.splitlines() if l}
        self.assertEqual(got, expected)

    def test_single_step_job(self):
        job = self._run(self._make_job(steps=("whatsapp",)))
        self.assertEqual(job.status, JobStatus.COMPLETED)
        self.assertEqual(job.steps.count(), 1)


@override_settings(MEDIA_ROOT=_MEDIA, VERIFIER_PROVIDER="mock")
class ViewTests(TestCase):
    def setUp(self):
        self.c = Client()

    def _upload(self):
        return self.c.post(reverse("verifier:start"), {
            "file": SimpleUploadedFile("contacts.csv", SAMPLE.encode()),
        })

    def test_pages_load(self):
        for name in ("dashboard", "start", "history"):
            self.assertEqual(self.c.get(reverse(f"verifier:{name}")).status_code, 200)

    def test_full_wizard_flow(self):
        r = self._upload()
        self.assertEqual(r.status_code, 302)
        job = VerificationJob.objects.latest("id")

        r = self.c.post(reverse("verifier:configure", args=[job.pk]), {
            "contact_type": "phone", "contact_column": "phone",
            "default_region": "US", "num_steps": "2",
            "service_1": "whatsapp", "service_2": "telegram",
        })
        self.assertEqual(r.status_code, 302)
        job.refresh_from_db()
        self.assertEqual(job.steps.count(), 2)
        self.assertEqual(job.eligible_contacts, 4)

        r = self.c.post(reverse("verifier:review", args=[job.pk]))
        self.assertEqual(r.status_code, 302)
        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.QUEUED)

        # drive worker
        for _ in range(50):
            if orchestrator.advance_job(job) in (orchestrator.DONE, orchestrator.FAILED):
                break
            job.refresh_from_db()
        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.COMPLETED)

        # status json + downloads
        self.assertEqual(self.c.get(reverse("verifier:status", args=[job.pk])).status_code, 200)
        for kind in ("valid", "all", "complete_valid", "complete_all"):
            r = self.c.get(reverse("verifier:download", args=[job.pk, kind]))
            self.assertEqual(r.status_code, 200)
            self.assertTrue(r.content)

    def test_configure_rejects_unsupported_combo(self):
        self._upload()
        job = VerificationJob.objects.latest("id")
        # Airbnb is phone-only; requesting it for email must be refused.
        r = self.c.post(reverse("verifier:configure", args=[job.pk]), {
            "contact_type": "email", "contact_column": "phone",
            "num_steps": "1", "service_1": "airbnb",
        }, follow=True)
        self.assertEqual(JobStep.objects.filter(job=job).count(), 0)

    def test_use_sample(self):
        r = self.c.get(reverse("verifier:sample"))
        self.assertEqual(r.status_code, 302)
        self.assertTrue(VerificationJob.objects.filter(file_name="sample_contacts.csv").exists())

    def test_delete_job(self):
        self._upload()
        job = VerificationJob.objects.latest("id")
        r = self.c.post(reverse("verifier:delete", args=[job.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertFalse(VerificationJob.objects.filter(pk=job.pk).exists())

    def test_clear_history_keeps_running_jobs(self):
        self._upload()
        done = VerificationJob.objects.latest("id")
        done.status = JobStatus.COMPLETED
        done.save()
        running = VerificationJob.objects.create(
            file_name="live.csv", contact_type=ContactType.PHONE,
            status=JobStatus.PROCESSING,
        )
        self.c.post(reverse("verifier:clear_history"))
        self.assertFalse(VerificationJob.objects.filter(pk=done.pk).exists())
        self.assertTrue(VerificationJob.objects.filter(pk=running.pk).exists())
