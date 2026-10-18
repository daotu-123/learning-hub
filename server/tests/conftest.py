"""pytest 共享配置。

鉴权中间件要求「非回环请求必须带令牌」。TestClient 的默认来源是 testclient
（非回环），所以所有测试都必须带令牌。这里在导入 main 之前把令牌固定下来，
避免测试依赖随机生成的 settings.json。
"""
import os

TEST_TOKEN = "test-token-for-pytest-only"

# 必须在 import main 之前设置：auth_token() 优先读环境变量
os.environ["WORKBENCH_AUTH_TOKEN"] = TEST_TOKEN
