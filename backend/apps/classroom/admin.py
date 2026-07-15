from django.contrib import admin

from .models import ClassCourse, ClassRoom, ClassStudent


@admin.register(ClassRoom)
class ClassRoomAdmin(admin.ModelAdmin):
    list_display = ("name", "course_names", "teacher", "invite_code", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("name", "invite_code")

    @admin.display(description="课程")
    def course_names(self, obj):
        return "、".join(obj.courses.values_list("name", flat=True))


@admin.register(ClassCourse)
class ClassCourseAdmin(admin.ModelAdmin):
    list_display = ("classroom", "course", "created_at")
    search_fields = ("classroom__name", "course__name")


@admin.register(ClassStudent)
class ClassStudentAdmin(admin.ModelAdmin):
    list_display = ("student", "classroom", "learn_status", "joined_at")
    list_filter = ("learn_status",)
