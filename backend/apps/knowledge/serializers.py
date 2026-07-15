from rest_framework import serializers

from .models import KnowledgeChunk, Material, QARecord


class MaterialSerializer(serializers.ModelSerializer):
    parse_status_display = serializers.CharField(source="get_parse_status_display", read_only=True)
    chunk_count = serializers.IntegerField(source="chunks.count", read_only=True)

    class Meta:
        model = Material
        fields = [
            "id", "course", "classroom", "file_name", "file_type", "file",
            "parse_status", "parse_status_display", "qa_open", "chunk_count", "created_at",
        ]
        read_only_fields = ["parse_status"]


class KnowledgeChunkSerializer(serializers.ModelSerializer):
    class Meta:
        model = KnowledgeChunk
        fields = ["id", "material", "course", "content", "page"]


class QARecordSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source="student.real_name", read_only=True)

    class Meta:
        model = QARecord
        fields = [
            "id", "course", "classroom", "student", "student_name",
            "question", "answer", "cited_chunks", "created_at",
        ]
        read_only_fields = ["student", "answer", "cited_chunks"]
