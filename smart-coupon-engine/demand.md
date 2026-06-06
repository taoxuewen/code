# demand.md — 需求记录

> 用户每次提出的需求，与我（AI）讨论后的结论，默认记录在这里。
> 目的：让任何新接手的人/AI 知道**每个功能是为了满足什么需求**而存在。
> 格式：按时间倒序，最新需求在最上面。
>
> 配套：`plan.md`（怎么做）、`debug.md`（出过什么 bug）。

---

## 需求模板（复制使用）

```
## [编号] 标题　—　YYYY-MM-DD
- **原始诉求**：用户原话/转述
- **背景**：为什么有这个需求
- **讨论结论**：最终怎么做、范围边界、取舍
- **影响范围**：涉及哪些模块 / plan.md 哪些条目
- **状态**：待开发 / 开发中 / 已交付
```

---

## [D6] 页面展示 uplift 模型评估指标 + 评估代码　—　2026-06-07
- **原始诉求**：页面上显示 uplift 模型构建好后的评估指标，并写好评估代码。
- **背景**：之前只输出推荐结果，看不到"模型本身好不好"。需要可量化、可展示的因果评估，让商家/自己判断模型是否可信。
- **讨论结论 / 实现**：
  - 难点：uplift 无直接真值（每个用户只能观测发券或不发券之一）。采用**因果评估**：在留出测试集上用观测 treatment/outcome 衡量"模型是否把券排给对的人"。
  - 新增 `models/evaluate.py`：
    - **分位 uplift 表**（按预测 uplift 降序分 10 档，看每档真实"处理组购买率−对照组购买率"，理想单调递减）——最直观。
    - **Qini 曲线 / Qini 系数 / AUUC**（累计增益，单一分数，>0 优于随机；手写梯形积分兼容 numpy 1.x/2.x）。
    - **子模型 AUC**（对照/处理模型判别力）。
  - `pipeline.build_recommendations` 增 `evaluate=True`：拆 30% 留出集、train 上拟合评估专用模型、test 上评估（不影响对客模型），结果放进 `RecommendResult.evaluation`。
  - API `_result_payload` 带上 `evaluation`；Web 结果页新增「Uplift 模型评估」卡片：指标卡（Top档提升倍数/Qini/AUUC/子模型AUC）+ 分位 uplift 柱状（正蓝负红、0 居中）+ 文字解读。
  - `scripts/trace_run.py` 增第 11 节同步打印评估；`sample_run_trace.md` 重生成。
  - **样本量观察**：评估在小样本下方差大、Qini 可能翻负。故 `/api/demo` 默认用户数 1500→**4000**，让展示更稳定可信。`evaluate.py` 设 `MIN_EVAL_SAMPLES=200`，不足则标记"不可用"而非报错。
- **影响范围**：新增 `models/evaluate.py`、`tests/test_evaluate.py`；改 `pipeline.py`、`api/main.py`、`web/*`、`scripts/trace_run.py`。plan 5.4/里程碑 M12。
- **状态**：已交付（2026-06-07）。pytest 25 项全绿（新增 5 项评估用例）。

---

## [D5] 全链路调试追踪日志：示例数据从输入到输出（含 uplift 模型内部）　—　2026-06-06
- **原始诉求**：想看示例数据从输入到输出、包括中间 uplift 模型调用得到的所有中间流程，打一份详细日志到一个文件里，看看一次本地调试整个中间日志长啥样。
- **背景**：之前只能看到最终结果，看不清链路中间发生了什么；需要一份"可读的全过程快照"用于理解/排查/给新 AI 讲解。
- **讨论结论 / 实现**：
  - 新增脚本 **`scripts/trace_run.py`**：用合成 3 表跑完整流程，把每一步中间结果写进一个 md 文件，并挑四象限各一个代表用户「全程跟踪」。
  - 覆盖步骤：0 配置 → 1 输入3表 → 2 适配(3表→orders/coupons+extra) → 3 特征工程+打标(含 ATE) → 4 模型训练 → **5 模型调用内部(对照概率/各面额处理概率/uplift=差值,逐用户)** → 6 全量 uplift 矩阵(按真实象限验证异质性) → 7 最优面额 → 8 预算分配 → 9 惊喜券权重+抽奖 → 10 最终推荐表。
  - 产物 **`sample_run_trace.md`** 随仓库提交，作为"标准调试日志样例"（可用脚本随时重生成）。
  - 用法：`python scripts/trace_run.py [用户数] [输出文件]`，默认 5000 用户 → `sample_run_trace.md`。
  - **观察记录**：小样本(数百)时两个 GBM 子模型噪声大、个体 uplift 失真(sure_thing 误为强正、sleeping_dog 误为正)；用户数提到数千后象限异质性回归正常(persuadable 最高、sleeping_dog 为负)。→ 调试/演示建议用 ≥3000 用户。
- **影响范围**：新增 `scripts/trace_run.py`、`sample_run_trace.md`；plan 目录树、README 指针。无引擎代码改动。
- **状态**：已交付（2026-06-06）。

---

## [D4] Windows 运行手册（供本地 AI 照做）+ 报错回写 debug.md　—　2026-06-06
- **原始诉求**：用户 Windows 本地也有 AI。需要把「如何在 Windows 直接运行」的详细流程写进 md 文件，保证本地 AI 读到就能跑起来；若执行出问题，让该 AI 把 bug 写进 debug.md。
- **背景**：跨机协作——本机（Linux）开发，用户 Windows 机器上的 AI 负责拉取并运行；需要一份「自包含、可被 AI 逐步执行」的运行说明，并形成 bug 回写闭环。
- **讨论结论 / 实现**：
  - 新增 **`RUN_ON_WINDOWS.md`**：面向人和 AI 的逐步 runbook——装 Python、取代码(git/zip)、虚拟环境(**用全路径 `.venv\Scripts\python.exe` 调用、不依赖 activate**，对 AI 无状态终端更稳)、装依赖、生成示例数据、三种运行方式、**常见问题速查表**、**给 AI 的硬性要求：报错按模板回写 debug.md**、以及更新方式。
  - 新增 **`start_windows.bat`**：双击一键建环境+装依赖+起服务（照顾人工操作）。
  - `debug.md`：加「给 Windows AI」提示；并补录首条真实 bug **B1**（`.gitignore` 误伤 data 源码包）作为格式范例。
  - README/plan 文档索引接入 `RUN_ON_WINDOWS.md`。
- **影响范围**：新增 `RUN_ON_WINDOWS.md`、`start_windows.bat`；改 `debug.md`、`README.md`、`plan.md`。纯文档/脚本，无引擎代码改动。
- **状态**：已交付（2026-06-06）。

---

## [D3] 改用「客户/商品/行为日志」3 表输入，跑通全流程　—　2026-06-06
- **原始诉求**：做 3 个示例 CSV——①客户基础属性（年龄、性别…）②商品基础属性（价格…）③行为日志（字段：uid、行为类型「浏览/加购/下单」、商品ID、行为时间）。并改代码，按这 3 表的输入跑通整条流程。
- **背景**：这是更贴近真实电商/小程序后台导出的数据结构；比 D1/D2 的 orders+coupons 两表更通用、更直观，便于商家对号入座。
- **关键讨论（券从哪来）**：3 表里没有优惠券信息，而 Uplift 必须有「发券/不发券」对照才能算（项目核心卖点）。**用户已拍板**：在行为日志的「行为类型」中**增加『领券』『用券』两种**，券面额放进可选列。→ 只用 3 张表、设计统一，且保住 Uplift 因果建模。详见对话中的三选一（选项 1）。
- **讨论结论 / 实现方案**：
  - **3 张表的数据契约**（列名支持中文/英文别名）：
    - 客户表 `customers`：`uid`(必) + `age/年龄`、`gender/性别`、`city/城市`、`register_date/注册日期`（均选填）。
    - 商品表 `products`：`item_id/商品ID`(必)、`price/价格`(必)、`category/品类`(选)。
    - 行为日志 `behavior`：`uid`(必)、`behavior_type/行为类型`(必，枚举：浏览/加购/下单/**领券/用券**)、`item_id/商品ID`(浏览/加购/下单需填)、`behavior_time/行为时间`(必)、`coupon_value/券面额`(领券/用券填)、`coupon_id/券ID`(选，用于配对领券↔用券，缺省自动生成)、`amount/金额`(下单选填，缺省取商品价格)。
  - **不重写引擎**：新增「摄取/适配层」`data/ingest.py`，把 3 表**转换成内部既有的 orders + coupons 两张表**（下单→订单；领券/用券→优惠券），下游 特征→模型→预算分配 完全复用。
  - **新增特征**（把新表的信息真正用起来）：客户属性（年龄、性别 one-hot、注册时长）+ 行为漏斗（浏览数、加购数、加购率、近 30 天浏览、交互商品均价≈价格敏感度代理）。经 `make_training_frame` 的 `extra_features` 通道并入特征矩阵。
  - **合成数据 + 示例 CSV**：新增 `data/synth_tables.py` 按四象限 uplift 结构生成 3 表；`scripts/gen_sample_data.py` 产出 `data/sample/{customers,products,behavior}.csv`。
  - **入口切换**：对客 Web 与 `/api/recommend`、`/api/demo` 改为 **3 表输入**（3 个上传位）。内部 `build_recommendations(orders,coupons)` 作为核心保留不变（测试仍覆盖）。
- **影响范围**：新增 `data/ingest.py`、`data/synth_tables.py`、`pipeline.recommend_from_tables`；改 `features/rfm.py`（extra_features 通道）、`api/main.py`（3 文件上传 + 新 demo）、`web/`（3 上传位）、`scripts/gen_sample_data.py`；plan 数据契约第 4 节、里程碑 M11。
- **状态**：已交付（2026-06-06）。3 表（客户/商品/行为日志）端到端跑通：`data/ingest.py` 适配成内部 orders+coupons 并派生客户/行为特征；Web 与 `/api/recommend`、`/api/demo` 切到 3 上传位；`scripts/gen_sample_data.py` 产出 `customers/products/behavior.csv` 示例；pytest 20 项全绿（新增 5 项 3 表用例）。

---

## [D2] 对客 Web 页面：上传行为数据 → 下载每客户推荐券面额　—　2026-06-06
- **原始诉求**：现在无法直观调试整条链路。把项目做成一个网站：高端但简洁的**苹果风**对客页面；第一版只做一个功能——用户上传客户行为数据（CSV 等格式），输出「每个客户应该发多少券面额」的表（Excel/CSV），可直接下载。文件上传/下载若需购买云服务请告知，或给免费替代方案。
- **背景**：
  - 命令行 + Streamlit 调试不够直观，需要一个能「自己上手玩、把数据丢进去就出结果」的入口。
  - 这也是面向商家做免费 POC 的门面——把"用你的数据帮你算一笔账"变成一次网页操作。
- **讨论结论**：
  - **不需要购买任何云服务**。第一版采用「内存直传直回」：浏览器上传 → 后端内存中跑完 pipeline → 结果表作为文件流直接回传下载，**文件不落盘、不持久化**，零成本、无存储桶配置。
    - 何时才需云存储（写入 plan 未来项）：要保留历史记录 / 大文件 / 异步批处理时，再上 Cloudflare R2（10GB 免费）或阿里云 OSS（免费额度）。
    - 网站部署：v1 本机 `uvicorn` 跑、`localhost` 调试；将来发公网再用 Render/Railway 免费档或便宜 VPS。
  - **输入**：沿用既有数据契约的两张表 `orders.csv` + `coupons.csv`（要算 uplift 必须有"历史是否发过券 + 之后是否购买"，缺一不可）。页面提供两个上传位 + 「用示例数据体验」一键 demo，照顾没数据的访客。
  - **输出**：每客户一行的推荐表，列＝`客户ID / 推荐券面额 / 是否发放 / 最优面额 / 预期增量购买概率 / 预期成本`；提供 **CSV 与 Excel(xlsx)** 两种下载。预算可在页面上调。
  - **风格**：苹果风——大留白、系统字体、克制配色、圆角与轻投影、单一主色、清晰的「上传 → 计算中 → 结果」三态。纯 HTML/CSS/JS，无构建步骤。
  - 复用现有 pipeline，不改算法；新增「Web 入口层」与一个「推荐表构建」薄函数。
- **影响范围**：新增 `web/`（前端）、`api/main.py` 新增 `POST /api/recommend`、`GET /api/demo` 与静态托管、`pipeline.py` 新增推荐表构建函数；新增依赖 `python-multipart`、`openpyxl`。详见 `plan.md` 第 2/3/5.12 节与里程碑 M10。
- **状态**：已交付（2026-06-06）。`uvicorn coupon_engine.api.main:app` 起服务、浏览器开 `localhost:8000` 即可上传数据/示例数据并下载推荐券面额表（CSV/Excel）；pytest 15 项回归全绿，Web 三路由真实端口冒烟通过。

---

## [D1] 落地实现智能发券引擎初版　—　2026-06-05
- **原始诉求**：阅读 `tracardi-growthbook-dify-智能营销引擎方案.md`，在 `plan.md` 写详细落地实现 plan，然后开始实现，构建「初版完整可运行、可跑通」的项目。同时建立 plan.md / demand.md / debug.md 三份文档，让任何新 AI 看到都能快速理解项目架构与思路。
- **背景**：方案文档目前只有商业 + 技术构想，没有任何代码。需要把构想变成可运行的最小产品，用来给商家做免费 POC、用真实数据「算一笔账」换取第一个客户。
- **讨论结论**：
  - 初版聚焦方案推荐的**极简版 MVP**（Python + CSV + Uplift 模型 + A/B + Streamlit/FastAPI），不部署 Tracardi/GrowthBook/Dify 重型平台。
  - 核心闭环：CSV → RFM 特征 → Uplift 模型 → 预算约束分配 + 惊喜券 → A/B 模拟与显著性检验 → LLM 文案 → 周报。
  - 必须**无真实数据、无 LLM key 也能跑通**（合成数据 + mock 文案）。
  - 三份 md 文档作为项目的「活文档」长期维护。
- **影响范围**：整个仓库；详见 `plan.md` 第 1-7 节。
- **状态**：初版已交付（2026-06-05）。极简版 MVP 端到端跑通，pytest 15 项全绿，D 组智能发券增量 GMV 统计显著。后续迭代（DragonNet、轻量版/完整版）见 plan.md 第 8 节。

---

## 工作约定（与用户确认）
- 代码与文档都放在 `/home/taoxuewen/code/smart-coupon-engine/`。
- 需要「传到 github」时，默认推送到 `git@github.com:taoxuewen/code.git`。
- 以后每次新需求，先聊清楚再默认记进本文件；规划变动同步进 `plan.md`；出 bug 修复后记进 `debug.md`。
