#!/bin/sh
# 后端容器启动入口：数据初始化 + 迁移 + 收集静态文件 + 启动 gunicorn
set -e

# SQLite 数据文件放到持久化卷 /app/data，再软链回 settings 期望的位置
mkdir -p /app/data
touch /app/data/db.sqlite3
ln -sf /app/data/db.sqlite3 /app/db.sqlite3

# 内置本地模型：镜像预置（/app/models，构建期 PRELOAD_MODELS=true 时存在）拷贝进
# 数据卷 /app/data/models；已存在的权重不覆盖（cp -n）。未预置时保持空目录，
# 首次使用惰性下载，或容器内 python manage.py download_models 预热。
mkdir -p /app/data/models
if [ -d /app/models ]; then
  cp -rn /app/models/. /app/data/models/ 2>/dev/null || true
fi

python manage.py migrate --noinput
python manage.py collectstatic --noinput

exec gunicorn config.wsgi:application \
  --bind 0.0.0.0:8000 \
  --workers 2 \
  --threads 2 \
  --timeout 180
