"""把 IANA 时区数据灌入 MySQL 的 `mysql.time_zone*` 四张表。

## 为什么必须做

项目 `USE_TZ=True`、`TIME_ZONE=Asia/Shanghai`。Django 在 MySQL 上做"按本地日分组"
（`TruncDate(tzinfo=...)`、`created_at__date__gte` 等）时会生成
`CONVERT_TZ(col, 'UTC', 'Asia/Shanghai')`。MySQL 的时区表若为空，
**CONVERT_TZ 返回 NULL** —— SQL 不报错，但 QA 看板、督管趋势、导出时间筛选会
静默变空。这是切换 MySQL 时最容易被忽略的坑。

## 为什么不用 mysql_tzinfo_to_sql

Windows 版工具只解析 TZif **v1** 数据块，而现代 tzdata（含 PyPI 的 `tzdata` 包）
是 **v2/slim** 格式：v1 头里的计数全为 0，工具会生成 `offset=0` 的空时区
（实测：`CONVERT_TZ('2026-10-30 00:00:00','UTC','Asia/Shanghai')` 原样返回，
而非 +8 小时）。这里直接解析 TZif v2 的 64 位数据块。

Docker 里的 mysql 官方镜像常缺 `/usr/share/zoneinfo`，同样用得上本脚本。

## 用法

    # 全量（推荐，600 个时区，几秒）
    python scripts/load_mysql_timezone.py --user root --password ***

    # 只灌应用实际用到的
    python scripts/load_mysql_timezone.py --user root --password *** --zones UTC Asia/Shanghai

    # 数据源可指定（默认取 venv 里 tzdata 包的 zoneinfo 目录）
    python scripts/load_mysql_timezone.py --user root --password *** --source-dir /usr/share/zoneinfo

写入的是 `mysql` 库，需要 root（或对 mysql.* 有写权限的账号）。
脚本可重复执行：同名时区先删后插，不会产生重复行。
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import struct
import sys

MAGIC = b"TZif"
# mysql.time_zone_transition.Transition_time 是 bigint（unix 秒），
# 负值（1970 年前的跃迁）MySQL 内部换算易出问题，统一从 0 起算。
TS_MIN = 0
TS_MAX = 2_147_483_647


def parse_tzif(path: str):
    """返回 (transitions[(unix_ts, type_idx)], types[(offset, is_dst, abbreviation)])。

    只取 v2/v3 的 64 位块；若文件只有 v1，则回退到 32 位块。
    """
    with open(path, "rb") as fh:
        data = fh.read()

    if data[:4] != MAGIC:
        raise ValueError("不是 TZif 文件")

    version = data[4:5]
    counts = struct.unpack(">6I", data[20:44])  # isut, isstd, leap, timecnt, typecnt, charcnt
    pos = 44

    def read_block(pos, time_size, counts):
        isutcnt, isstdcnt, leapcnt, timecnt, typecnt, charcnt = counts
        if timecnt:
            fmt = ">%d%s" % (timecnt, "q" if time_size == 8 else "l")
            times = struct.unpack(fmt, data[pos : pos + time_size * timecnt])
            pos += time_size * timecnt
            idxs = list(data[pos : pos + timecnt])
            pos += timecnt
        else:
            times, idxs = (), []
        types = []
        for _ in range(typecnt):
            offset, is_dst, abbr_idx = struct.unpack(">lBB", data[pos : pos + 6])
            pos += 6
            types.append([offset, is_dst, abbr_idx])
        abbrs = data[pos : pos + charcnt]
        pos += charcnt
        pos += leapcnt * (time_size + 4)
        pos += isstdcnt + isutcnt
        for t in types:
            start = t[2]
            end = abbrs.find(b"\x00", start)
            t[2] = abbrs[start : end if end >= 0 else len(abbrs)].decode("ascii", "replace")
        return times, idxs, [tuple(t) for t in types], pos

    if version in (b"2", b"3", b"4"):
        # 先跳过 v1 块，再读 64 位块
        _, _, _, pos = read_block(pos, 4, counts)
        counts = struct.unpack(">6I", data[pos + 20 : pos + 44])
        pos += 44
        times, idxs, types, _ = read_block(pos, 8, counts)
    else:
        times, idxs, types, _ = read_block(pos, 4, counts)

    raw = list(zip(times, idxs))
    # 只保留 unix 秒可安全表达的范围（负值/超 2038 的历史跃迁跳过）
    transitions = [(ts, idx) for ts, idx in raw if TS_MIN <= ts <= TS_MAX]
    if not transitions and types:
        # 全部跃迁都在 1970 之前（部分非洲/美洲老时区）：补一条 1970 起点，
        # 取当时应生效的类型，否则该时区在 MySQL 里无法解析
        prior = [t for t in raw if t[0] < TS_MIN]
        transitions = [(TS_MIN, prior[-1][1] if prior else 0)]
    return transitions, types


def discover(source_dir: str) -> list[tuple[str, str]]:
    """返回 [(时区名, 文件路径)]，跳过非 TZif 的说明文件。"""
    found = []
    for root, _dirs, files in os.walk(source_dir):
        for name in files:
            path = os.path.join(root, name)
            try:
                with open(path, "rb") as fh:
                    if fh.read(4) != MAGIC:
                        continue
            except OSError:
                continue
            zone = os.path.relpath(path, source_dir).replace(os.sep, "/")
            found.append((zone, path))
    return sorted(found)


def default_source_dir() -> str:
    try:
        import tzdata

        return os.path.join(os.path.dirname(tzdata.__file__), "zoneinfo")
    except ImportError:
        for candidate in ("/usr/share/zoneinfo", "/usr/lib/zoneinfo"):
            if os.path.isdir(candidate):
                return candidate
    raise SystemExit("找不到时区数据：请 pip install tzdata 或用 --source-dir 指定")


def main():
    parser = argparse.ArgumentParser(description="把 IANA 时区灌入 MySQL 时区表")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=3306)
    parser.add_argument("--user", default="root")
    parser.add_argument("--password", default="")
    parser.add_argument("--zones", nargs="*", help="只灌这些时区（默认全部）")
    parser.add_argument("--source-dir", default=None)
    args = parser.parse_args()

    import MySQLdb

    source_dir = args.source_dir or default_source_dir()
    zones = discover(source_dir)
    if args.zones:
        wanted = set(args.zones)
        zones = [(z, p) for z, p in zones if z in wanted]
        missing = wanted - {z for z, _ in zones}
        if missing:
            raise SystemExit(f"数据源里找不到这些时区：{sorted(missing)}")
    if not zones:
        raise SystemExit("没有可导入的时区")

    print(f"数据源：{source_dir}，时区 {len(zones)} 个")

    conn = MySQLdb.connect(
        host=args.host, port=args.port, user=args.user,
        passwd=args.password, db="mysql", charset="utf8mb4",
    )
    # TIMESTAMP 列的写入按会话时区解释，固定 UTC 才能与 unix 时间戳对齐
    cur = conn.cursor()
    cur.execute("SET time_zone = '+00:00'")

    total_tr = 0
    for zone, path in zones:
        try:
            transitions, types = parse_tzif(path)
        except Exception as exc:  # 个别非常规文件跳过，不中断整批
            print(f"  ! {zone}: 解析失败 {exc}")
            continue

        # 先解析出 time_zone_id 再按 id 删（MySQL 不允许对系统表做带子查询的写锁定）
        cur.execute("SELECT Time_zone_id FROM time_zone_name WHERE Name = %s", [zone])
        existing = cur.fetchone()
        if existing:
            old_id = existing[0]
            for table in (
                "time_zone_transition",
                "time_zone_transition_type",
                "time_zone_name",
                "time_zone",
            ):
                cur.execute(f"DELETE FROM {table} WHERE Time_zone_id = %s", [old_id])

        cur.execute("INSERT INTO time_zone (Use_leap_seconds) VALUES ('N')")
        tz_id = cur.lastrowid
        cur.execute(
            "INSERT INTO time_zone_name (Name, Time_zone_id) VALUES (%s, %s)", [zone, tz_id]
        )
        if types:
            cur.executemany(
                "INSERT INTO time_zone_transition_type "
                "(Time_zone_id, Transition_type_id, Offset, Is_DST, Abbreviation) "
                "VALUES (%s, %s, %s, %s, %s)",
                [(tz_id, i, off, isdst, abbr) for i, (off, isdst, abbr) in enumerate(types)],
            )
        if transitions:
            cur.executemany(
                "INSERT INTO time_zone_transition "
                "(Time_zone_id, Transition_time, Transition_type_id) VALUES (%s, %s, %s)",
                [(tz_id, ts, idx) for ts, idx in transitions],
            )
        total_tr += len(transitions)

    conn.commit()
    cur.execute("SELECT COUNT(*) FROM time_zone_name")
    names = cur.fetchone()[0]
    cur.execute("SELECT CONVERT_TZ('2026-10-30 00:00:00','UTC','Asia/Shanghai')")
    probe = cur.fetchone()[0]
    cur.close()
    conn.close()

    print(f"完成：时区 {names} 个，跃迁 {total_tr} 条")
    print(f"校验 CONVERT_TZ('2026-10-30 00:00:00','UTC','Asia/Shanghai') = {probe}")
    if str(probe).startswith("2026-10-30 08:00"):
        print("时区表可用。")
        return 0
    print("警告：校验值不符（期望 2026-10-30 08:00:00），请检查数据源。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
