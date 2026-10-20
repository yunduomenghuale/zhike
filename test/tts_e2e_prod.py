# 生产 E2E：配音链路实测（备份→清页→合成→断言→恢复）
import json
import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from apps.courses.models import TeachingVideo  # noqa: E402
from apps.ai.services import synthesize_audio_for_video  # noqa: E402
from apps.ai.models import AICallLog  # noqa: E402

BACKUP = "/tmp/tts-e2e-scripts-backup.json"

# 1) 选一个有讲解稿的视频（优先页数多、缺配音的）
video = (
    TeachingVideo.objects.filter(scripts__isnull=False)
    .exclude(scripts=[])
    .order_by("-id")
    .first()
)
if video is None:
    print("RESULT=NO_VIDEO")
    raise SystemExit(0)

scripts = video.scripts or []
script_pages = [i for i, item in enumerate(scripts) if (item.get("script") or "").strip()]
if not script_pages:
    print("RESULT=NO_SCRIPT_PAGES")
    raise SystemExit(0)

# 2) 备份原始 scripts
with open(BACKUP, "w", encoding="utf-8") as f:
    json.dump(scripts, f, ensure_ascii=False)

# 3) 清掉第一页的 audio_url/audio_error（模拟未配音页）
idx = script_pages[0]
original_url = scripts[idx].pop("audio_url", None)
scripts[idx].pop("audio_error", None)
video.scripts = scripts
video.save(update_fields=["scripts", "updated_at"])
print(f"SETUP video={video.id} page={idx} cleared_url={'yes' if original_url else 'none'}")

# 4) 实测合成 1 页
try:
    ok = synthesize_audio_for_video(video, limit=1)
except Exception as exc:
    print(f"RESULT=EXCEPTION {type(exc).__name__}: {str(exc)[:300]}")
    ok = -1

# 5) 断言
video.refresh_from_db()
page = video.scripts[idx]
audio_url = page.get("audio_url")
audio_error = page.get("audio_error")
log = (
    AICallLog.objects.filter(scene=AICallLog.Scene.TTS)
    .order_by("-id")
    .first()
)
print(
    "ASSERT "
    f"ok={ok} "
    f"has_url={bool(audio_url)} "
    f"url_prefix={(audio_url or '')[:60]} "
    f"has_error={bool(audio_error)} "
    f"error={(audio_error or '')[:120]} "
    f"log_model={getattr(log, 'model_name', None)} "
    f"log_success={getattr(log, 'success', None)} "
    f"log_is_mock={getattr(log, 'is_mock', None)}"
)

# 6) 恢复原始 scripts
with open(BACKUP, "r", encoding="utf-8") as f:
    original = json.load(f)
video.scripts = original
video.save(update_fields=["scripts", "updated_at"])
video.refresh_from_db()
restored = video.scripts == original
print(f"RESTORED={restored} pages={len(video.scripts or [])}")
print("RESULT=DONE")
