"""热更新通道完整性校验回归测试。

背景（2026-10-18 审查）：hotupdate.ts 走明文 HTTP、无签名/哈希校验，
WwwHandler 缓存优先于内置 —— 同网段改一份 JS 就能写入 App 并拿到
window.Native 的全部 13 个原生能力（读写 SharedPreferences、设闹钟、
往相册写任意文件）。

修复后：/webversion 的文件清单带每文件 sha256，客户端逐文件校验，
不通过则跳过（回退内置资源）。
"""
import hashlib
import re

import pytest
from fastapi.testclient import TestClient

from conftest import TEST_TOKEN

AUTH = {"X-Token": TEST_TOKEN}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@pytest.fixture(scope="module")
def client():
    from main import app

    return TestClient(app, client=("192.168.1.50", 51234))


def test_webversion_files_carry_sha256(client):
    r = client.get("/api/hub/webversion", headers=AUTH)
    assert r.status_code == 200, r.text
    data = r.json()
    assert isinstance(data.get("files"), list) and data["files"], "文件清单不应为空"
    for item in data["files"]:
        assert isinstance(item, dict), f"清单项应为对象，实际 {type(item)}"
        assert "name" in item and item["name"], item
        assert SHA256_RE.match(item.get("sha256") or ""), f"sha256 格式不合法: {item}"


def test_sha256_matches_actual_content(client):
    """清单里的 sha256 必须等于 /webfile 返回内容的哈希（否则客户端会拒绝更新）。"""
    r = client.get("/api/hub/webversion", headers=AUTH)
    files = r.json()["files"]
    # 取一个文本文件验证
    target = next((f for f in files if f["name"].endswith((".html", ".js", ".css"))), None)
    assert target, "清单里应至少有一个文本文件"

    fr = client.get("/api/hub/webfile/" + target["name"], headers=AUTH)
    assert fr.status_code == 200, fr.text
    content = fr.json()["content"]
    actual = hashlib.sha256(content.encode("utf-8")).hexdigest()
    assert actual == target["sha256"], (
        f"{target['name']} 的内容哈希与清单不一致：清单={target['sha256']} 实际={actual}"
    )


def test_webfile_requires_token(client):
    """热更新通道必须受鉴权保护，否则攻击者可直接改写 App 代码。"""
    r = client.get("/api/hub/webversion")
    assert r.status_code == 401, r.text
