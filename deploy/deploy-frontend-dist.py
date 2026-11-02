#!/usr/bin/env python
"""前端产物一键发布到机房生产（192.168.3.145:8088）。

只用一条 SSH 连接：备份现网 dist → 清空 → tar 流式解压 → md5 双端校验。
dist 是 bind mount（/data/zhike-v2/frontend/dist -> /usr/share/nginx/html），
替换文件即生效，**不需要重启任何容器**。

前置：
    pip install paramiko      # 本项目用 backend/venv（系统 python 缺 _cffi_backend）
    export SSH_PASS=<服务器密码>

用法：
    cd frontend && npm run build
    python deploy/deploy-frontend-dist.py frontend/dist

参数：
    argv[1]  本地 dist 目录（脚本自动打包成临时 tar.gz）
    argv[2]  可选，入口 js 文件名（如 index-BIaH-1H0.js），给了就额外校验其 md5
"""
import hashlib
import os
import sys
import tarfile
import tempfile
import time

try:
    import paramiko
except ImportError:  # 本机 paramiko 不在 venv 里，靠 PYTHONPATH=D:/tmp/pylibs 引入
    print("缺少 paramiko：用 `PYTHONPATH=D:/tmp/pylibs ./backend/venv/Scripts/python.exe deploy/deploy-frontend-dist.py ...` 运行")
    raise SystemExit(1)

HOST = os.environ.get("SSH_HOST", "192.168.3.145")
USER = os.environ.get("SSH_USER", "lymatrix2020")
PWD = os.environ.get("SSH_PASS", "")
DIST = "/data/zhike-v2/frontend/dist"
BACKUP_DIR = "/data/zhike-v2/backups"


def run(cli, cmd, timeout=300):
    _in, out, err = cli.exec_command(cmd, timeout=timeout)
    o = out.read().decode("utf-8", "replace")
    e = err.read().decode("utf-8", "replace")
    rc = out.channel.recv_exit_status()
    return rc, o.strip(), e.strip()


def md5_file(path):
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main():
    if not PWD:
        print("缺少 SSH_PASS 环境变量")
        return 1
    local_dist = sys.argv[1] if len(sys.argv) > 1 else "frontend/dist"
    entry_js = sys.argv[2] if len(sys.argv) > 2 else ""
    if not os.path.isdir(local_dist):
        print(f"目录不存在：{local_dist}")
        return 1

    # 打包（保留 ./ 相对路径，解压到 dist 即还原结构）
    tmp_tar = os.path.join(tempfile.gettempdir(), f"zhike-dist-{int(time.time())}.tar.gz")
    with tarfile.open(tmp_tar, "w:gz") as tf:
        for name in os.listdir(local_dist):
            tf.add(os.path.join(local_dist, name), arcname=name)
    size = os.path.getsize(tmp_tar)
    print(f"[0/4] 已打包 {local_dist} -> {size / 1024:.0f} KB")

    ts = time.strftime("%Y%m%d-%H%M%S")
    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    cli.connect(HOST, port=22, username=USER, password=PWD,
                look_for_keys=False, allow_agent=False, timeout=20,
                banner_timeout=30, auth_timeout=30)
    try:
        # 1) 备份现网 dist（回滚用）
        rc, _o, e = run(cli, f"cd /data/zhike-v2 && sudo tar czf {BACKUP_DIR}/frontend-dist-{ts}.tar.gz -C frontend/dist .")
        if rc != 0:
            print(f"[1/4] 备份失败 rc={rc} {e[:300]}")
            return 1
        print(f"[1/4] 已备份 {BACKUP_DIR}/frontend-dist-{ts}.tar.gz")

        # 2) 清空 dist：保留目录本身，bind mount 的 inode 不能失效
        rc, _o, e = run(cli, f"sudo find {DIST} -mindepth 1 -delete")
        if rc != 0:
            print(f"[2/4] 清空失败 rc={rc} {e[:300]}")
            return 1
        print("[2/4] dist 已清空")

        # 3) tar 流式解压（单连接，不用 SFTP 也不分块）
        t0 = time.time()
        stdin, stdout, stderr = cli.exec_command(f"sudo tar xzf - -C {DIST}", timeout=600)
        with open(tmp_tar, "rb") as fh:
            for block in iter(lambda: fh.read(1 << 16), b""):
                stdin.write(block)
        stdin.flush()
        stdin.channel.shutdown_write()
        rc = stdout.channel.recv_exit_status()
        err = stderr.read().decode("utf-8", "replace").strip()
        if rc != 0:
            print(f"[3/4] 解压失败 rc={rc} {err[:300]}")
            return 1
        print(f"[3/4] 已解压，用时 {time.time() - t0:.1f}s")

        # 4) 校验：index.html + 入口 JS 双端 md5 必须一致
        rc, out, _e = run(cli, f"md5sum {DIST}/index.html")
        remote_index = out.split()[0] if out else ""
        local_index = md5_file(os.path.join(local_dist, "index.html"))
        ok = remote_index == local_index
        print(f"[4/4] index.html md5 本地={local_index} 远端={remote_index} -> {'一致' if ok else '不一致'}")
        if entry_js:
            rc, out3, _e = run(cli, f"md5sum {DIST}/assets/{entry_js}")
            remote_js = out3.split()[0] if out3 else ""
            local_js = md5_file(os.path.join(local_dist, "assets", entry_js))
            ok = ok and remote_js == local_js
            print(f"      入口 JS  md5 本地={local_js} 远端={remote_js} -> {'一致' if remote_js == local_js else '不一致'}")
        print(f"      回滚：sudo tar xzf {BACKUP_DIR}/frontend-dist-{ts}.tar.gz -C {DIST}")
        return 0 if ok else 2
    finally:
        cli.close()
        try:
            os.remove(tmp_tar)
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(main())
