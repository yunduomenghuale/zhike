from django.contrib import admin

from .models import (
    Lab,
    LabAnswer,
    LabAttemptToken,
    LabQuestion,
    LabReport,
    LabSchedule,
    LabSubmission,
    LabTemplate,
)

admin.site.register(LabTemplate)
admin.site.register(Lab)
admin.site.register(LabSchedule)
admin.site.register(LabSubmission)
admin.site.register(LabQuestion)
admin.site.register(LabAnswer)
admin.site.register(LabAttemptToken)
admin.site.register(LabReport)
