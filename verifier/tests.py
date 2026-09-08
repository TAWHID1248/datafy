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

    def test_bad_row_region_falls_back_to_default(self):
        # Country column pointing at non-region data (e.g. the phone column
        # itself) must not poison the parse.
        val, reason = normalize_phone(
            "12403507481", default_region="US", row_region="12403507481"
        )
        self.assertEqual(val, "+12403507481")
        self.assertEqual(reason, "")

    def test_valid_row_region_overrides_default(self):
        val, _ = normalize_phone("2071838750", default_region="US", row_region="gb")
        self.assertEqual(val, "+442071838750")

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

    def test_step_download(self):
        job = self._run(self._make_job())
        step1 = job.steps.first()
        checked = orchestrator.download_step_txt(job, step1)
        lines = checked.strip().splitlines()
        self.assertEqual(lines[0], "contact\tnormalized\tstatus")
        # one row per contact checked at step 1
        self.assertEqual(len(lines) - 1, step1.checked)
        # valid-only export lists exactly the step's valid contacts
        valid = orchestrator.download_step_txt(job, step1, valid_only=True)
        got = {l for l in valid.splitlines() if l}
        self.assertEqual(len(got), step1.valid)


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


class CatalogCheckerTests(TestCase):
    def test_basic_checker_is_default(self):
        self.assertEqual(catalog.task_type_for("whatsapp", "phone"), "ws")
        self.assertEqual(catalog.task_type_for("whatsapp", "phone", "basic"), "ws")
        self.assertEqual(catalog.task_type_for("telegram", "phone"), "tg")

    def test_richer_checkers_resolve(self):
        self.assertEqual(catalog.task_type_for("whatsapp", "phone", "activity"), "ws_active")
        self.assertEqual(catalog.task_type_for("whatsapp", "phone", "profile"), "ws_avatar")
        self.assertEqual(catalog.task_type_for("telegram", "phone", "activity"), "tg_active")
        self.assertEqual(catalog.task_type_for("telegram", "phone", "profile"), "tg_avatar")

    def test_unknown_checker_is_rejected(self):
        self.assertIsNone(catalog.task_type_for("whatsapp", "phone", "nope"))
        self.assertIsNone(catalog.task_type_for("amazon", "email", "activity"))

    def test_checkers_for_lists_basic_first(self):
        keys = [c[0] for c in catalog.checkers_for("whatsapp", "phone")]
        self.assertEqual(keys, ["basic", "activity", "profile"])
        keys = [c[0] for c in catalog.checkers_for("amazon", "email")]
        self.assertEqual(keys, ["basic"])
        self.assertEqual(catalog.checkers_for("spotify", "phone"), [])


@override_settings(MEDIA_ROOT=_MEDIA, VERIFIER_PROVIDER="mock")
class CheckerSelectionViewTests(TestCase):
    def setUp(self):
        self.c = Client()
        self.c.post(reverse("verifier:start"), {
            "file": SimpleUploadedFile("contacts.csv", SAMPLE.encode()),
        })
        self.job = VerificationJob.objects.latest("id")

    def _configure(self, **extra):
        data = {
            "contact_type": "phone", "contact_column": "phone",
            "default_region": "US", "num_steps": "1", "service_1": "whatsapp",
        }
        data.update(extra)
        return self.c.post(reverse("verifier:configure", args=[self.job.pk]), data)

    def test_defaults_to_basic_checker_when_omitted(self):
        self.assertEqual(self._configure().status_code, 302)
        step = self.job.steps.get()
        self.assertEqual((step.task_type, step.checker), ("ws", "basic"))
        self.assertEqual(step.display_label, "WhatsApp")

    def test_selected_checker_sets_task_type_and_label(self):
        self.assertEqual(self._configure(checker_1="activity").status_code, 302)
        step = self.job.steps.get()
        self.assertEqual((step.task_type, step.checker), ("ws_active", "activity"))
        self.assertEqual(step.checker_label, "Number Activity")
        self.assertEqual(step.display_label, "WhatsApp · Number Activity")

    def test_invalid_checker_rejected(self):
        self._configure(checker_1="bogus")
        self.assertEqual(self.job.steps.count(), 0)

    def test_configure_page_exposes_checker_options(self):
        r = self.c.get(reverse("verifier:configure", args=[self.job.pk]))
        self.assertContains(r, "Number Activity")
        self.assertContains(r, 'name="checker_${i}"')


class CheckNumberParseTests(TestCase):
    """Result parsing must cope with the richer checkers' extra/capitalised columns."""

    def _provider(self):
        from unittest import mock
        from .providers import checknumber
        with override_settings(CHECKNUMBER_API_KEY="k", CHECKNUMBER_BASE_URL="http://x"):
            p = checknumber.CheckNumberProvider()
        return p, mock

    def _fetch(self, csv_text):
        from .providers.base import PollResult
        p, mock = self._provider()
        with mock.patch.object(p, "_download_rows") as dl:
            import csv, io
            dl.return_value = list(csv.DictReader(io.StringIO(csv_text)))
            res = p.fetch(PollResult(state="exported", done=True, result_url="u"),
                          ["+14155552671", "+14155552672", "+14155552673"])
        return {s.value: s.outcome for s in res.statuses}

    def test_basic_columns(self):
        out = self._fetch("number,activated\n14155552671,yes\n14155552672,no\n")
        self.assertEqual(out["+14155552671"], Outcome.VALID)
        self.assertEqual(out["+14155552672"], Outcome.INVALID)
        self.assertEqual(out["+14155552673"], Outcome.UNRESOLVED)

    def test_activity_extra_columns_ignored(self):
        out = self._fetch(
            "number,activated,activetime,activedays,business\n"
            "14155552671,yes,2026-01-01,3,false\n14155552672,no,,,\n"
        )
        self.assertEqual(out["+14155552671"], Outcome.VALID)
        self.assertEqual(out["+14155552672"], Outcome.INVALID)

    def test_profile_capitalised_phone_header(self):
        out = self._fetch(
            "Phone,activated,uid,Gender,Age\n14155552671,yes,1,m,30\n14155552672,no,,,\n"
        )
        self.assertEqual(out["+14155552671"], Outcome.VALID)
        self.assertEqual(out["+14155552672"], Outcome.INVALID)


class RegionListTests(TestCase):
    def test_every_supported_region_has_a_name_and_dial_code(self):
        import phonenumbers
        from . import regions
        popular, rest = regions.region_choices()
        codes = {r["code"] for r in popular + rest}
        self.assertEqual(codes, set(phonenumbers.SUPPORTED_REGIONS))
        self.assertTrue(all(r["dial"] > 0 and r["name"] != r["code"] for r in popular + rest))
        self.assertEqual([r["code"] for r in popular][:2], ["US", "GB"])

    def test_configure_page_lists_all_countries(self):
        c = Client()
        c.post(reverse("verifier:start"), {
            "file": SimpleUploadedFile("contacts.csv", SAMPLE.encode()),
        })
        job = VerificationJob.objects.latest("id")
        r = c.get(reverse("verifier:configure", args=[job.pk]))
        for needle in ('value="DE">Germany (+49)', 'value="BR">Brazil (+55)',
                       'value="JP">Japan (+81)', 'value="BD">Bangladesh (+880)'):
            self.assertContains(r, needle)
