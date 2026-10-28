from django.contrib import admin

from .models import (
    Lab,
    LabAttemptToken,
    LabReport,
    LabSchedule,
    LabSubmission,
    LabTemplate,
)

admin.site.register(LabTemplate)
admin.site.register(Lab)
admin.site.register(LabSchedule)
admin.site.register(LabSubmission)
admin.site.register(LabAttemptToken)
admin.site.register(LabReport)
