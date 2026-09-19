"""随机参数种子生成：服务端确定性生成，提交评分时复算标准答案。"""
import hashlib
import json


def generate_seed(lab, student_id: int, attempt: int) -> dict:
    """按 lab.random_config 生成随机参数。

    random_config 形如：
        {"ranges": {"s1": [1, 9], "s2": [1, 9]}, "algo": "hash"}
    以 (lab_id, student_id, attempt) 为熵源确定性生成，同一次作答的 seed 可复现、可复核。
    """
    config = lab.effective_random_config or {}
    ranges = config.get("ranges") or {}
    if not ranges:
        return {}

    base = f"{lab.id}:{student_id}:{attempt}"
    seed: dict = {}
    for idx, (key, span) in enumerate(sorted(ranges.items())):
        try:
            low, high = int(span[0]), int(span[1])
        except (TypeError, ValueError, IndexError):
            continue
        if high < low:
            low, high = high, low
        digest = hashlib.sha256(f"{base}:{key}".encode()).hexdigest()
        value = low + int(digest[:8], 16) % (high - low + 1)
        seed[key] = value
    seed["_meta"] = {"base": base, "version": 1, "config": json.dumps(ranges, ensure_ascii=False)}
    return seed


def derive_expected(seed: dict, template_code: str) -> dict:
    """由 seed 推导实验的标准参数（供提交时一致性校验/报告展示）。

    具体推导公式与静态页约定一致：如 ARP 实验网段 = 192.168.{s1}.0 / 192.168.{s2}.0。
    这里提供通用网段推导，实验页可按 template_code 扩展。
    """
    if not seed:
        return {}
    s1 = seed.get("s1")
    s2 = seed.get("s2")
    expected = {}
    if s1 is not None:
        expected["subnet1"] = f"192.168.{s1}.0"
    if s2 is not None:
        expected["subnet2"] = f"192.168.{s2}.0"
    return {"template": template_code, "params": expected}
