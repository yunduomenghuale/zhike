# 造一份未交卷的新考试（学生端答题页截图用）+ 查 vision 开关
import os, sys, django
BASE = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'backend')
sys.path.insert(0, os.path.abspath(BASE))
os.chdir(os.path.abspath(BASE))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from datetime import timedelta
from django.utils import timezone
from django.contrib.auth import get_user_model
import requests
from rest_framework_simplejwt.tokens import RefreshToken

U = get_user_model()
t101 = U.objects.get(username='t101')
H = {'Authorization': f'Bearer {RefreshToken.for_user(t101).access_token}'}
API = 'http://localhost:8005/api'

# 0) vision 开关
r = requests.get(f'{API}/qa-records/vision-capability/', headers=H, timeout=30)
print('vision ->', r.status_code, r.text[:120])

# 1) 创建考试（draft）
now = timezone.now()
payload = {
    'course': 7, 'classroom': 3,
    'name': '第2章 Java编程基础·章节测验',
    'start_at': (now - timedelta(hours=1)).isoformat(),
    'end_at': (now + timedelta(days=7)).isoformat(),
    'duration': 30, 'status': 'draft',
    'shuffle_questions': False, 'shuffle_options': False,
    'show_analysis_after': True, 'allow_resubmit': False,
}
r = requests.post(f'{API}/exams/', headers=H, json=payload, timeout=60)
print('exam create ->', r.status_code, str(r.json())[:200])
eid = r.json()['data']['id']

# 2) 手动组卷（84/85 单选 + 99/101 多选，共 10 分）
compose = {'mode': 'manual', 'questions': [
    {'question_id': 84, 'score': 2},
    {'question_id': 85, 'score': 2},
    {'question_id': 99, 'score': 3},
    {'question_id': 101, 'score': 3},
]}
r = requests.post(f'{API}/exams/{eid}/compose/', headers=H, json=compose, timeout=60)
print('compose ->', r.status_code, str(r.json())[:160])

# 3) 发布
r = requests.patch(f'{API}/exams/{eid}/', headers=H, json={'status': 'published'}, timeout=60)
print('publish ->', r.status_code, str(r.json())[:160])

from apps.exams.models import Exam
e = Exam.objects.get(id=eid)
print(f'final: exam#{eid} {e.name} status={e.status} total={e.total_score}')
