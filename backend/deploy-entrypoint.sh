#!/bin/sh
# 后端容器启动入口：数据初始化 + 迁移 + 收集静态文件 + 启动 gunicorn
set -e

# 数据库形态由 DATABASE_URL 决定（见 config/settings.py）
case "${DATABASE_URL:-sqlite}" in
  mysql*)
    # compose 的 healthcheck 已保证 mysql 起来了，这里再自旋一次兜住"容器重启但库还在初始化"
    echo "[entrypoint] 等待 MySQL 可连接…"
    python - <<'PY'
import os
import sys
import time
from urllib.parse import unquote, urlparse

import MySQLdb

url = os.environ["DATABASE_URL"]
parsed = urlparse(url)
for attempt in range(1, 61):
    try:
        MySQLdb.connect(
            host=parsed.hostname or "mysql",
            port=parsed.port or 3306,
            user=unquote(parsed.username or ""),
            passwd=unquote(parsed.password or ""),
            db=parsed.path.lstrip("/"),
            connect_timeout=3,
        ).close()
        print(f"[entrypoint] MySQL 就绪（第 {attempt} 次尝试）", flush=True)
        sys.exit(0)
    except Exception as exc:  # noqa: BLE001 - 启动期只关心能否连上
        print(f"[entrypoint] 第 {attempt}/60 次连接失败：{exc}", flush=True)
        time.sleep(2)
sys.exit("[entrypoint] MySQL 60 次重试仍不可用，退出")
PY
    ;;
  *)
    # SQLite：数据文件放到持久化卷 /app/data，再软链回 settings 期望的位置
    mkdir -p /app/data
    touch /app/data/db.sqlite3
    ln -sf /app/data/db.sqlite3 /app/db.sqlite3
    ;;
esac

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
