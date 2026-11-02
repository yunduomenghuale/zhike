# 手册 v2 增量演示数据：班级美化 + 学生补员 + Java 教学资源(三类) + 题图
import os, sys, django
BASE = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'backend')
sys.path.insert(0, os.path.abspath(BASE))
os.chdir(os.path.abspath(BASE))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

import requests
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import RefreshToken
from apps.classroom.models import ClassRoom, ClassStudent
from apps.courses.models import CourseResource, Course

U = get_user_model()
log = []

# 1) E2E 残留班级改名
ClassRoom.objects.filter(id=17).update(name='计算机应用2025级-1班')
log.append('班级 #17 → 计算机应用2025级-1班')

# 2) A 班补 3 名学生（一名休学，用于展示学籍状态）
new_students = [('2026003', '陈思远', 'enrolled'), ('2026004', '林小雨', 'suspended'), ('2026005', '赵一鸣', 'enrolled')]
for username, real_name, edu in new_students:
    u, created = U.objects.get_or_create(
        username=username,
        defaults=dict(real_name=real_name, role='student', edu_status=edu, enrollment_year=2026, duration_years=4))
    if created:
        u.set_password('Zk' + username[-6:].rjust(6, '0'))
        u.save()
    ClassStudent.objects.get_or_create(
        classroom_id=3, student=u, defaults=dict(learn_status='active'))
    log.append(f'学生 {username} {real_name} edu={edu} created={created} → A班')

# 3) 删除 course7 下内容错位的旧资源（计算机网络主题）
old = CourseResource.objects.filter(course_id=7)
log.append(f'删除旧资源 {old.count()} 个: {list(old.values_list("id", "title"))}')
old.delete()

# 4) 造 Java 三类资源
t101 = U.objects.get(username='t101')
H = {'Authorization': f'Bearer {RefreshToken.for_user(t101).access_token}'}
API = 'http://localhost:8005/api'
SAMPLE = os.path.join(os.path.dirname(__file__), 'sample_resources')

def upload_resource(kind, title, intro, file_path=None, path=''):
    data = {'course': 7, 'kind': kind, 'title': title, 'intro': intro}
    if path:
        data['path'] = path
        r = requests.post(f'{API}/course-resources/', headers=H, data=data, timeout=120)
    else:
        with open(file_path, 'rb') as f:
            r = requests.post(f'{API}/course-resources/', headers=H, data=data,
                              files={'file': (os.path.basename(file_path), f)}, timeout=300)
    print(f'  [{kind}] {title} -> {r.status_code} {str(r.json())[:130]}')
    return r.json().get('data', {}).get('id')

rid_mind = upload_resource('mindmap', 'Java 程序设计知识体系导图',
                          '按语言基础 / 面向对象 / 运行机制三块组织的课程知识地图，适合章末整体回顾。',
                          file_path=os.path.join(SAMPLE, 'java-mindmap.html'))
rid_demo = upload_resource('demo', 'JDK 开发环境配置演示',
                          '三步演示安装 JDK、配置 Path 与编译运行 Hello World，可点击步骤切换查看。',
                          file_path=os.path.join(SAMPLE, 'jdk-demo.html'))
rid_doc = upload_resource('document', '第1章 Java语言概述-课件.pdf',
                         '第 1 章课堂讲义原件，含 Java 发展、三大平台与 JDK 环境配置要点。',
                         file_path='media/ppt/94ccf8e741604c65895d3a230a25352c.pdf')

# 5) 发布导图与演示（学生端可见），文档保持未发布以便展示发布开关两态
for rid in (rid_mind, rid_demo):
    if rid:
        r = requests.post(f'{API}/course-resources/{rid}/publish/', headers=H, timeout=60)
        print('  publish', rid, r.status_code)

# 6) 给题 84（JDK 环境变量）上传题图
from apps.questions.models import Question
q = Question.objects.get(id=84)
img_path = 'media/ppt_pages/7c8fab098572a0c5/slide-008.png'
if os.path.exists(img_path):
    with open(img_path, 'rb') as f:
        r = requests.post(f'{API}/question-images/upload/', headers=H,
                          files={'file': ('jdk-env.png', f, 'image/png')}, timeout=60)
    print('  qimage upload ->', r.status_code, str(r.json())[:100])
    if r.status_code < 400:
        p = r.json()['data']['path']
        rr = requests.patch(f'{API}/questions/84/', headers=H, json={'image': p}, timeout=60)
        print('  q84 image patch ->', rr.status_code, str(rr.json())[:100])
else:
    print('  qimage source missing', img_path)

print('--- verify ---')
for r in CourseResource.objects.filter(course_id=7):
    print(f'  #{r.id} {r.kind} {r.title} pub={r.is_published} file={r.file_name or r.path}')
print('class3 students:', [(cs.student.username, cs.student.real_name, cs.student.edu_status, cs.learn_status)
                           for cs in ClassStudent.objects.filter(classroom_id=3).select_related('student')])
print('q84 image:', Question.objects.get(id=84).image)
print('\n'.join(log))
