import os, sys, django
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()
from apps.knowledge.models import QARecord

base = dict(course_id=5, classroom_id=None, catalog_id=None, session='e2e-seed',
            student_id=14, cited_chunks=[], rewritten_question='', turn_index=0)
rows = [
    QARecord(question='这条回答完全没提到重点，请重新说明排序的稳定性',
             answer='抱歉，我未能找到相关课程资料片段。',
             context_snapshot={'budgets': {}, 'chunks': 0, 'degraded_level': 0},
             feedback=-1, **base),
    QARecord(question='作业要求里的提交截止时间是哪天',
             answer='资料中未检索到相关内容，建议查看课程公告。',
             context_snapshot={'budgets': {}, 'chunks': 0, 'degraded_level': 0},
             feedback=-1, **base),
    QARecord(question='课程里提到的分治策略具体怎么用',
             answer='根据提供的资料片段，分治策略的核心是将问题分解为子问题递归求解。',
             context_snapshot={'budgets': {'total': 3000}, 'chunks': 4, 'degraded_level': 2},
             **base),
    QARecord(question='考试范围和题型有哪些',
             answer='根据资料片段，考试范围涵盖课程各章节核心知识点。',
             context_snapshot={'budgets': {'total': 3000}, 'chunks': 2, 'degraded_level': 4},
             **base),
    QARecord(question='这张图里的流程图怎么理解',
             answer='你上传的图片我暂时无法直接识别内容，但可以根据文字描述尝试分析。',
             context_snapshot={'budgets': {}, 'chunks': 0, 'degraded_level': 0},
             skip_retrieval=True, **base),
]
QARecord.objects.bulk_create(rows)
qa = QARecord.objects.all()
print('total now:', qa.count())
print('disliked:', qa.filter(feedback=-1).count())
print('skip_retrieval:', qa.filter(skip_retrieval=True).count())
print('empty(non-skip):', qa.filter(cited_chunks=[], skip_retrieval=False).count())
