#!/bin/bash
# 智课系统V2 生产备份脚本（部署位置：服务器 /data/zhike-v2/backups/backup.sh，由 crontab 每日 03:30 调用）
# 本文件是仓库内的版本，便于追溯；部署时 cp 到上述路径并 chmod +x。
# 注意：Windows 编辑后必须 `sed -i 's/\r$//'` 去掉 CR，否则报 `/bin/bash^M: 解释器错误`。
#
# 智课系统V2 每日备份：MySQL 逻辑备份 + media 增量同步
#
# 数据库：mysqldump
#   --single-transaction  一致性快照（InnoDB），不锁表，可在线跑
#   --quick               逐行读取，避免整表读进内存
#   --routines --triggers 带上存储过程/触发器，恢复才完整
#   目标库是 192.10.0.3 的 test-mysql80 容器（bnet-test 网络），
#   宿主机没装 mysql 客户端，所以借 mysql:8.0 镜像在同网络里执行。
#   MYSQL_PWD 传密码，避免出现在 ps 命令行里。
# 保留：14 天（db-YYYYMMDD.sql.gz），更旧的自动删。
# media：rsync 增量同步，**不带 --delete**（主目录误删时不连带删备份）。
set -euo pipefail

BASE=/data/zhike-v2
STAMP=$(date +%Y%m%d)
DB_HOST=192.10.0.3
DB_USER=root
DB_PASS='test@2021'
DB_NAME=zk
OUT_DIR="$BASE/data/backups/mysql"
OUT="$OUT_DIR/db-$STAMP.sql.gz"

mkdir -p "$OUT_DIR" "$BASE/backups/media"
rm -f "$OUT"   # 支持当日重跑

# 1) 逻辑备份（管道任一环失败都算失败：set -o pipefail）
sudo docker run --rm --network bnet-test -e MYSQL_PWD="$DB_PASS" mysql:8.0 \
  mysqldump -h"$DB_HOST" -u"$DB_USER" \
    --single-transaction --quick --routines --triggers \
    --default-character-set=utf8mb4 --no-tablespaces \
    "$DB_NAME" | gzip > "$OUT"

# 2) 三重校验：gzip 完整、文件非空、含建表语句（挡住"连不上库却生成空壳"的假成功）
gzip -t "$OUT"
[ -s "$OUT" ] || { echo "!! 备份为空：$OUT"; exit 1; }
# 用 grep -c（读完整个流）而不是 -q：-q 命中即退出会让 zcat 收到 SIGPIPE，
# 配合 set -o pipefail 会被判成失败（经典的假告警）
TABLE_COUNT=$(zcat "$OUT" | grep -c "^CREATE TABLE" || true)
[ "$TABLE_COUNT" -gt 0 ] || { echo "!! 备份不含建表语句，疑似导出失败"; exit 1; }

# 3) media 增量
rsync -a "$BASE/media/" "$BASE/backups/media/"

# 4) 清理 14 天前的库备份
find "$OUT_DIR" -name 'db-*.sql.gz' -mtime +14 -delete

echo "$(date '+%F %T') backup done: $(basename "$OUT") $(du -h "$OUT" | cut -f1), tables=$TABLE_COUNT"
