from django.contrib import admin

from .models import Catalog, Course, PPTResource, TeachingVideo


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ("name", "teacher", "term", "status", "created_at")
    list_filter = ("status", "term")
    search_fields = ("name",)


@admin.register(Catalog)
class CatalogAdmin(admin.ModelAdmin):
    list_display = ("title", "course", "parent", "order", "is_published")
    list_filter = ("course", "is_published")
    search_fields = ("title",)


@admin.register(PPTResource)
class PPTResourceAdmin(admin.ModelAdmin):
    list_display = ("file_name", "course", "catalog", "parse_status", "version", "is_active")
    list_filter = ("parse_status", "is_active")


@admin.register(TeachingVideo)
class TeachingVideoAdmin(admin.ModelAdmin):
    list_display = ("catalog", "course", "gen_status", "is_published", "published_at")
    list_filter = ("gen_status", "is_published")
