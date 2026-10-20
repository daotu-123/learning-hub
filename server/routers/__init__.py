# -*- coding: utf-8 -*-
"""routers 包：按域拆分的 FastAPI 路由（M1b-2）。

约定：
- 每个模块一个 APIRouter，路径/方法/响应结构与拆分前逐字一致；
- 模块之间可以互相 import（如 ai 聚合多个域），但**不许 import main**
  （会成环）；共享的东西放 common.py；
- 注册顺序由 main.py 的 include_router 顺序决定，见 main.py 顶部说明。
"""
