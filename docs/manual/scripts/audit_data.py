# 手册演示数据盘点脚本（一次性）
import os, sys, django
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', 'backend'))
os.chdir(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'backend'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()
from django.apps import apps
from django.contrib.auth import get_user_model
from django.db.models import Count

User = get_user_model()
print("== Users by role ==")
for r in User.objects.values('role').annotate(n=Count('id')):
    print(r)
print("teachers:", list(User.objects.filter(role='teacher').values_list('username', 'real_name')))
print("students:", list(User.objects.filter(role='student').values_list('username', 'real_name')[:30]))

print("\n== Model counts (non-zero) ==")
for m in apps.get_models():
    try:
        n = m.objects.count()
    except Exception as e:
        n = f"ERR {e}"
    if n:
        print(f"{m._meta.app_label}.{m.__name__}: {n}")
