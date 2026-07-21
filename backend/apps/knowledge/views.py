import json

from django.http import StreamingHttpResponse
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated

from apps.ai.services import ingest_material, knowledge_qa, knowledge_qa_stream
from apps.common.permissions import IsTeacherOrReadOnly
from apps.common.response import api_response
from apps.common.viewsets import BaseModelViewSet

from .models import KnowledgeChunk, Material, QARecord
from .serializers import MaterialSerializer, QARecordSerializer


def _sse(payload: dict) -> str:
    """封装成 SSE data 帧。"""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


# 图片问题允许的最大 base64 长度（约 4MB 原图）
_MAX_IMAGE_B64_LEN = 5_600_000


def _validate_image(value):
    """校验可选的 base64 图片（data URL）。返回 (image_b64 或 None, 错误信息或 None)。"""
    if not value:
        return None, None
    if not isinstance(value, str) or not value.startswith("data:image/"):
        return None, "图片格式不正确"
    if len(value) > _MAX_IMAGE_B64_LEN:
        return None, "图片过大，请压缩后再试"
    return value, None


class MaterialViewSet(BaseModelViewSet):
    serializer_class = MaterialSerializer
    permission_classes = [IsTeacherOrReadOnly]
    filterset_fields = ["course", "classroom", "parse_status", "qa_open"]

    def get_queryset(self):
        return Material.objects.all()

    def perform_create(self, serializer):
        """上传即自动识别类型并解析入库（需求 T-K-01/02）。"""
        from .extractor import detect_file_type

        material = serializer.save()
        if material.file and not material.file_type:
            material.file_type = detect_file_type(material.file_name or material.file.name)
            material.save(update_fields=["file_type", "updated_at"])
        ingest_material(material)

    @action(detail=True, methods=["post"], url_path="reparse")
    def reparse(self, request, pk=None):
        """重新解析入库：抽取→切分→向量化→写入知识库片段（需求 T-K-03）。"""
        material = self.get_object()
        count = ingest_material(material)
        return api_response({"chunk_count": count}, message="资料已重新入库")

    @action(detail=True, methods=["post"], url_path="toggle-qa")
    def toggle_qa(self, request, pk=None):
        """开启/关闭该资料对学生的自由提问（需求 T-K-04）。"""
        material = self.get_object()
        material.qa_open = not material.qa_open
        material.save(update_fields=["qa_open", "updated_at"])
        return api_response({"qa_open": material.qa_open}, message="已更新开放状态")


class QARecordViewSet(BaseModelViewSet):
    serializer_class = QARecordSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ["course", "classroom", "student"]

    def get_queryset(self):
        user = self.request.user
        qs = QARecord.objects.select_related("student")
        # 教师看全部（用于了解疑难点），学生只看自己的历史提问
        if user.is_authenticated and user.is_student:
            qs = qs.filter(student=user)
        return qs

    @action(detail=False, methods=["post"], url_path="ask")
    def ask(self, request):
        """学生向课程知识库自由提问（需求 S-K-01/02/04）。

        基于课程资料检索 + 大模型回答；无相关资料时提示资料不足，不编造。
        """
        course_id = request.data.get("course")
        classroom_id = request.data.get("classroom")
        question = request.data.get("question", "").strip()
        if not question:
            return api_response(message="问题不能为空", code=400, status=400)
        image_b64, error = _validate_image(request.data.get("image"))
        if error:
            return api_response(message=error, code=400, status=400)

        answer, cited = knowledge_qa(course_id=course_id, question=question, image_b64=image_b64)
        record = QARecord.objects.create(
            course_id=course_id,
            classroom_id=classroom_id,
            catalog_id=request.data.get("catalog"),
            session=str(request.data.get("session") or "")[:64],
            student=request.user,
            question=question,
            answer=answer,
            cited_chunks=cited,
        )
        return api_response(QARecordSerializer(record).data, message="回答完成")

    @action(detail=False, methods=["post"], url_path="ask-stream")
    def ask_stream(self, request):
        """流式问答（SSE）：逐 token 返回回答，边生成边显示。

        事件序列：meta(引用片段) -> 若干 delta(文本片段) -> done。
        生成结束后落库为一条 QARecord。
        """
        course_id = request.data.get("course")
        classroom_id = request.data.get("classroom")
        catalog_id = request.data.get("catalog")
        session = str(request.data.get("session") or "")[:64]
        question = (request.data.get("question") or "").strip()
        if not question:
            return api_response(message="问题不能为空", code=400, status=400)
        image_b64, error = _validate_image(request.data.get("image"))
        if error:
            return api_response(message=error, code=400, status=400)
        user = request.user

        def event_stream():
            full, cited = [], []
            try:
                for evt in knowledge_qa_stream(
                    course_id=course_id, question=question, catalog_id=catalog_id, image_b64=image_b64
                ):
                    if evt["type"] == "meta":
                        cited = evt["cited"]
                        yield _sse({"type": "meta", "cited": cited})
                    elif evt["type"] == "delta":
                        full.append(evt["text"])
                        yield _sse({"type": "delta", "text": evt["text"]})
            except Exception as exc:  # 生成中出错也要通知前端
                yield _sse({"type": "error", "message": str(exc)})
            answer = "".join(full)
            try:
                QARecord.objects.create(
                    course_id=course_id,
                    classroom_id=classroom_id,
                    catalog_id=catalog_id,
                    session=session,
                    student=user,
                    question=question,
                    answer=answer,
                    cited_chunks=cited,
                )
            except Exception:
                pass
            yield _sse({"type": "done"})

        resp = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
        resp["Cache-Control"] = "no-cache"
        resp["X-Accel-Buffering"] = "no"  # 关闭 nginx/代理缓冲，保证逐段下发
        return resp
