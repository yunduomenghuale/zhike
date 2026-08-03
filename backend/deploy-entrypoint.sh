#!/bin/sh
# 后端容器启动入口：数据初始化 + 迁移 + 收集静态文件 + 启动 gunicorn
set -e

# SQLite 数据文件放到持久化卷 /app/data，再软链回 settings 期望的位置
mkdir -p /app/data
touch /app/data/db.sqlite3
ln -sf /app/data/db.sqlite3 /app/db.sqlite3

python manage.py migrate --noinput
python manage.py collectstatic --noinput

exec gunicorn config.wsgi:application \
  --bind 0.0.0.0:8000 \
  --workers 2 \
  --threads 2 \
  --timeout 180
