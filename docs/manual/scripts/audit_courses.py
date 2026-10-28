# 课程完整性盘点 v2（精简输出）
import os, sys, django
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', 'backend'))
os.chdir(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'backend'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from apps.courses.models import Course, Catalog, PPTResource, TeachingVideo
from apps.classroom.models import ClassRoom, ClassCourse, ClassStudent
from apps.questions.models import Question
from apps.homework.models import Homework, HomeworkSubmission
from apps.exams.models import Exam, ExamSubmission
from apps.knowledge.models import Material

for c in Course.objects.all():
    cats = Catalog.objects.filter(course=c)
    ppts = PPTResource.objects.filter(course=c)
    vids = TeachingVideo.objects.filter(ppt__course=c)
    print(f"\n== Course {c.id}: {c.name} | teacher={c.teacher.username} status={c.status} ==")
    for cat in cats:
        ppt = ppts.filter(catalog=cat).first()
        v = vids.filter(ppt__catalog=cat)
        v_done = v.filter(gen_status='done').count()
        pub = v.filter(is_published=True).count()
        pages = len(ppt.parsed_pages or []) if ppt else 0
        ppt_info = f"ppt#{ppt.id} {ppt.parse_status} pages={pages}" if ppt else "no-ppt"
        print(f"   cat#{cat.id} '{cat.title[:20]}' pub={cat.is_published} {ppt_info} videos={v.count()}(done={v_done},pub={pub})")
    print(f"  materials={Material.objects.filter(course=c).count()} questions={Question.objects.filter(course=c).count()}")
    hws = Homework.objects.filter(course=c)
    print(f"  homeworks:", [(h.id, h.title[:16], h.status) for h in hws])
    exs = Exam.objects.filter(course=c)
    print(f"  exams:", [(e.id, e.name[:16], e.status) for e in exs])
    for cc in ClassCourse.objects.filter(course=c):
        cls = cc.classroom
        stus = ClassStudent.objects.filter(classroom=cls).select_related('student')
        print(f"  class#{cls.id} '{cls.name}' students={stus.count()}", [s.student.username for s in stus])
    for h in hws:
        subs = HomeworkSubmission.objects.filter(homework=h)
        if subs.exists():
            print(f"   hw#{h.id} subs:", [(s.student.username, s.correct_status) for s in subs])
    for e in exs:
        subs = ExamSubmission.objects.filter(exam=e)
        if subs.exists():
            print(f"   exam#{e.id} subs:", [(s.student.username, s.status, str(s.total_score), 'rel' if s.score_released else 'unrel') for s in subs])
