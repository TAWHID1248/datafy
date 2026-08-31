from django.contrib import admin

from .models import Contact, JobStep, SourceRow, StepResult, VerificationJob


class JobStepInline(admin.TabularInline):
    model = JobStep
    extra = 0


@admin.register(VerificationJob)
class VerificationJobAdmin(admin.ModelAdmin):
    list_display = ("id", "file_name", "contact_type", "status",
                    "total_rows", "created_at")
    list_filter = ("status", "contact_type")
    search_fields = ("file_name",)
    inlines = [JobStepInline]


@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    list_display = ("normalized", "raw_value", "is_eligible",
                    "flag_reason", "final_outcome", "job")
    list_filter = ("is_eligible", "final_outcome")
    search_fields = ("normalized", "raw_value")


admin.site.register([JobStep, SourceRow, StepResult])
