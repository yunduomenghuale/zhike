# 手册演示数据准备（一把梭）：改名美化 + 题目归位 + 错题本 + 成绩发布 + 知识库资料上传 + 新作业
import os, sys, django
BASE = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'backend')
sys.path.insert(0, os.path.abspath(BASE))
os.chdir(os.path.abspath(BASE))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from datetime import timedelta
from django.utils import timezone
from django.contrib.auth import get_user_model
from apps.courses.models import Course
from apps.classroom.models import ClassRoom
from apps.questions.models import Question, WrongNote, AnswerRecord
from apps.exams.models import ExamSubmission

U = get_user_model()
log = []

# 1) 改名美化（避免截图出现 E2E 残留名）
Course.objects.filter(id=5).update(name='计算机网络')
ClassRoom.objects.filter(id=1).update(name='网络2026届-1班')
ClassRoom.objects.filter(id=6).update(name='数据结构兴趣班')
log.append('改名完成：Course5→计算机网络，班1→网络2026届-1班，班6→数据结构兴趣班')

# 2) 题目归位：course7 里混入的 7 道数据结构题 → course6（按内容分章）
move = {60: 6, 61: 6, 62: 6, 66: 6, 63: 7, 64: 7, 65: 7}  # qid → course6 的 catalog_id
for qid, catid in move.items():
    Question.objects.filter(id=qid).update(course_id=6, catalog_id=catid)
log.append('7 道数据结构题迁至 course6')

# 3) 错题本（学生 2026001，course7）
stu = U.objects.get(username='2026001')
c7 = Course.objects.get(id=7)
wrong_spec = [
    (82, {'key': 'A'}, 'A', 'B'),
    (83, {'key': 'A'}, 'A', 'C'),
    (97, {'keys': ['A', 'B']}, 'A、B', 'A、B、C'),
]
for qid, ans_json, mine_txt, correct_txt in wrong_spec:
    q = Question.objects.get(id=qid)
    WrongNote.objects.get_or_create(
        student=stu, course=c7, stem=q.stem,
        defaults=dict(catalog=q.catalog, my_answer=mine_txt, correct_answer=correct_txt, analysis=q.analysis or ''))
    AnswerRecord.objects.get_or_create(
        student=stu, question=q, scene='practice',
        defaults=dict(student_answer=ans_json, is_correct=False, score=0, submitted_at=timezone.now()))
log.append('错题本 ×3 完成')

# 4) 考试 26 发布成绩（学生端「答题情况回顾」前置）
n = ExamSubmission.objects.filter(exam_id=26, score_released=False).update(score_released=True)
log.append(f'exam26 成绩发布 {n} 条')
print('\n'.join(log))

# 5) API 部分（走真实接口）
import requests
from rest_framework_simplejwt.tokens import RefreshToken
t101 = U.objects.get(username='t101')
H = {'Authorization': f'Bearer {RefreshToken.for_user(t101).access_token}'}
API = 'http://localhost:8005/api'

# 5a) 知识库资料 ×2（课件原件 PDF，上传即解析+向量化）
uploads = [
    ('media/ppt/94ccf8e741604c65895d3a230a25352c.pdf', '第1章-Java语言概述-课件.pdf', 11),
    ('media/ppt/d92b6030e433491c915fb237586f49d8.pdf', '第2章-Java语言编程基础-课件.pdf', 12),
]
for path, name, catid in uploads:
    if not os.path.exists(path):
        print('MISSING FILE:', path)
        continue
    with open(path, 'rb') as f:
        r = requests.post(f'{API}/materials/', headers=H,
                          files={'file': (name, f, 'application/pdf')},
                          data={'course': 7, 'catalog': catid, 'file_name': name}, timeout=600)
    print('upload', name, '->', r.status_code, str(r.json())[:160])

# 5b) 新作业「第1章 Java概述·课后练习」（A 班，published，7 天后截止，学生端演示待完成/提交）
payload = {
    'classroom': 3, 'course': 7,
    'title': '第1章 Java概述·课后练习',
    'description': '请独立完成以下练习，截止前可多次修改提交。',
    'mode': 'questions', 'status': 'published',
    'deadline': (timezone.now() + timedelta(days=7)).isoformat(),
    'question_items': [
        {'question': 82, 'score': 2},
        {'question': 83, 'score': 2},
        {'question': 97, 'score': 3},
        {'question': 98, 'score': 3},
    ],
}
r = requests.post(f'{API}/homeworks/', headers=H, json=payload, timeout=60)
print('homework create ->', r.status_code, str(r.json())[:200])

# 6) 验证汇总
from apps.knowledge.models import Material, KnowledgeChunk
from apps.homework.models import Homework
print('--- verify ---')
print('course7 materials:', Material.objects.filter(course_id=7).values_list('id', 'file_name', 'parse_status'))
print('course7 chunks:', KnowledgeChunk.objects.filter(material__course_id=7).count())
print('course7 homeworks:', list(Homework.objects.filter(course_id=7).values_list('id', 'title', 'status')))
print('questions: course7 =', Question.objects.filter(course_id=7).count(), ', course6 =', Question.objects.filter(course_id=6).count())
print('2026001 wrongnotes:', WrongNote.objects.filter(student=stu).count(),
      'answer_records:', AnswerRecord.objects.filter(student=stu).count())
