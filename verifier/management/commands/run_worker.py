"""Background worker that advances verification jobs.

Run alongside the web server:

    python manage.py run_worker

It repeatedly picks up QUEUED/PROCESSING jobs and drives each through the
orchestrator state machine (submit -> poll -> fetch -> next step -> finalize).
No Celery/Redis required: the provider is already async, so a single polling
loop is enough for an internal-scale tool.

Use ``--once`` to advance all active jobs a single pass and exit (handy for
tests or a cron tick).
"""

import time

from django.core.management.base import BaseCommand

from verifier.models import JobStatus, VerificationJob
from verifier.services import orchestrator


class Command(BaseCommand):
    help = "Advance queued/processing verification jobs."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true",
                            help="Make one pass over active jobs and exit.")
        parser.add_argument("--interval", type=float, default=3.0,
                            help="Seconds between polls of the job queue.")
        parser.add_argument("--poll-wait", type=float, default=5.0,
                            help="Seconds to wait when a step is submitted "
                                 "but the provider is not done yet.")

    def handle(self, *args, **opts):
        active = (JobStatus.QUEUED, JobStatus.PROCESSING)
        once = opts["once"]
        interval = opts["interval"]
        poll_wait = opts["poll_wait"]

        if not once:
            self.stdout.write(self.style.SUCCESS("Worker started. Ctrl-C to stop."))

        while True:
            jobs = list(VerificationJob.objects.filter(status__in=active))
            for job in jobs:
                self._drive(job, poll_wait, once)
            if once:
                return
            time.sleep(interval)

    def _drive(self, job, poll_wait, once):
        """Advance a single job until it needs to wait or is done."""
        while True:
            try:
                signal = orchestrator.advance_job(job)
            except Exception as exc:  # noqa: BLE001 - surface any failure on the job
                job.status = JobStatus.FAILED
                job.error = f"{type(exc).__name__}: {exc}"
                job.stage = "Failed"
                job.save(update_fields=["status", "error", "stage"])
                self.stderr.write(self.style.ERROR(f"Job {job.id} failed: {exc}"))
                return
            job.refresh_from_db()
            if signal == orchestrator.CONTINUE:
                continue
            if signal == orchestrator.WAIT:
                if once:
                    return
                time.sleep(poll_wait)
                continue
            # DONE or FAILED
            self.stdout.write(
                f"Job {job.id} -> {job.get_status_display()}"
            )
            return
