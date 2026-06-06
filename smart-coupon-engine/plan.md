# plan.md — 智能发券引擎 落地实现规划

> 本文件是**整个项目的活地图**。任何新加入的人（或 AI）只读这一份，就能理解：我们在做什么、为什么这么做、代码长什么样、下一步往哪走。
> 规划一旦有变动，**必须同步更新本文件**（见末尾「变更日志」）。
>
> 配套文件：
> - `demand.md` — 需求记录（用户每次提的需求 + 讨论结论）
> - `debug.md` — bug 记录（每次报错 → 定位 → 修复）
> - `test.md` — 测试记录（所有用例清单 + 历次运行结果）
> - `RUN_ON_WINDOWS.md` — Windows 运行手册（人/AI 可直接照做；含一键脚本与排错表）
> - 业务方案原文：`../tracardi-growthbook-dify-智能营销引擎方案.md`

---

## 0. 一句话项目定义

**用 Uplift 因果模型算清楚「这个用户该不该发券、发多少券」，再用「惊喜券」抽奖外壳规避大数据杀熟，并用 A/B 实验证明省了多少钱。**

我们卖的不是软件，是「省下来的券成本」。

---

## 1. 范围界定：我们先做哪一版？

业务方案给了三档技术栈，本仓库**初版只做「极简版 MVP」**（方案 1.3 节 + 七、Phase 1）：

| 档位 | 技术栈 | 本仓库是否实现 |
|------|--------|----------------|
| 极简版（0-3 客户） | Python + CSV + pandas + scipy + LLM API + Streamlit | ✅ **就是本仓库** |
| 轻量版（3-10 客户） | PostHog + LiteLLM + Metabase + FastAPI | ⏳ 后续阶段 |
| 完整版（10+ 客户） | Tracardi + GrowthBook + Dify | ⏳ 远期 |

**为什么从极简版起步**（方案原文论证）：
- 95% 的中小私域商家只有「订单表 + 优惠券表」，没有数据仓库、没有埋点。
- 这两张表就足够算出 RFM 特征、训练 uplift 模型。
- 第一个客户是靠「用他的数据帮他算一笔账」换来的，不需要部署重型平台。
- 目标：单台 2C4G、Docker 一键启动、约 2000 行 Python、可独立跑通。

**初版交付的核心闭环：**
```
商家 CSV（订单+优惠券）
   → 特征工程（RFM + 券行为）
   → Uplift 模型（每用户×每面额的增量分数）
   → 预算约束分配 + 惊喜券权重
   → A/B 模拟 + 显著性检验（证明 vs 不发/随机/规则）
   → LLM 生成券文案 & 策略解释
   → 输出「能在周会上汇报」的报告
```

---

## 2. 系统架构（初版）

```
                         smart-coupon-engine（单 Python 服务）
┌──────────────────────────────────────────────────────────────────────┐
│                                                                        │
│  入口层                                                                 │
│   ├── web/ + api/main.py   对客网站（苹果风）：上传数据 → 下载推荐券面额   │
│   ├── app/dashboard.py     Streamlit：上传 CSV → 看报告 → 下载结果       │
│   ├── api/main.py          FastAPI：在线推理 /score、/allocate          │
│   └── scripts/run_pipeline.py  CLI：离线批量跑全流程                     │
│                                  │                                      │
│                                  ▼                                      │
│  编排层  pipeline.py  ── 把下面各层串成端到端流程 ──                      │
│                                  │                                      │
│   ┌──────────┬──────────┬───────┴────┬──────────┬──────────┐          │
│   ▼          ▼          ▼            ▼          ▼          ▼          │
│ data/      features/   models/    allocation/ experiment/  llm/+report/ │
│ 加载校验    RFM 特征    Uplift     预算+惊喜券   A/B+检验     文案+周报     │
│ 合成数据                                                                 │
│                                                                        │
│  配置层  config.py（面额档位、预算、分组比例、LLM 开关等全局参数）          │
└──────────────────────────────────────────────────────────────────────┘
```

设计原则：
- **每层只依赖下层、可单独测试**；层与层之间传 pandas DataFrame / 简单 dataclass。
- **无真实数据也能跑**：`data/synth.py` 生成合成数据，CI 和 demo 都用它。
- **LLM 可关闭**：没有 API key 时走 mock 文案，整条流程不阻塞。
- **模型可插拔**：`models/registry.py` 注册表，初版用 Two-Model，后续接 DragonNet 只需新增一个类。

---

## 3. 目录结构

```
smart-coupon-engine/
├── plan.md / demand.md / debug.md / README.md
├── requirements.txt
├── pyproject.toml            # 包配置，src 布局
├── Dockerfile
├── docker-compose.yml
├── .env.example              # LLM key 等（不提交真实 .env）
├── data/
│   └── sample/               # 合成样例 CSV（gen 出来，方便 demo）
│       ├── orders.csv
│       └── coupons.csv
├── src/coupon_engine/
│   ├── config.py             # 全局配置（dataclass + 默认值）
│   ├── data/
│   │   ├── loader.py         # 读取+校验订单/优惠券 CSV（内部 2 表契约）
│   │   ├── ingest.py         # 对外 3 表(客户/商品/行为)校验 + 适配成内部 2 表（D3）
│   │   ├── synth.py          # 合成数据生成器（订单/优惠券，含真实 uplift 机制）
│   │   └── synth_tables.py   # 合成 3 表（客户/商品/行为日志，D3）
│   ├── features/
│   │   └── rfm.py            # RFM + 券行为特征
│   ├── models/
│   │   ├── base.py           # UpliftModel 抽象基类
│   │   ├── two_model.py      # 双模型 uplift（默认）
│   │   ├── evaluate.py       # uplift 评估：Qini/AUUC/分位uplift/子模型AUC（D6）
│   │   └── registry.py       # 模型注册/工厂
│   ├── allocation/
│   │   ├── budget.py         # 预算约束下的面额分配
│   │   └── surprise.py       # uplift→奖池权重（惊喜券）
│   ├── experiment/
│   │   └── abtest.py         # A/B/C/D 分流模拟 + scipy 检验
│   ├── llm/
│   │   └── copywriter.py     # 券文案/策略解释（可 mock）
│   ├── report/
│   │   └── builder.py        # 周报（文本/markdown）
│   ├── api/
│   │   └── main.py           # FastAPI
│   └── pipeline.py           # 端到端编排
├── web/                       # 对客网站前端（苹果风，纯静态，无构建）
│   ├── index.html            # 单页：上传 → 计算中 → 结果下载
│   ├── styles.css            # 苹果风样式
│   └── app.js                # 上传/调用 /api/recommend/下载
├── app/dashboard.py          # Streamlit
├── scripts/
│   ├── gen_sample_data.py    # 生成 data/sample（2表+3表）
│   ├── run_pipeline.py       # CLI 跑全流程
│   └── trace_run.py          # 全链路调试追踪：打印输入→输出每步中间结果（D5）
├── sample_run_trace.md        # trace_run.py 产出的标准调试日志样例（D5）
└── tests/                    # pytest
```

---

## 4. 数据契约（最重要的对齐点）

**字段命名是整个项目的接口**，改动需谨慎。项目有两套契约：

- **对外输入（D3 起，对客主入口）**：客户 / 商品 / 行为日志 **3 张表**（见 4.0），更贴近真实电商导出。
- **内部契约（引擎核心）**：订单 `orders` + 优惠券 `coupons` **2 张表**（见 4.1/4.2）。`data/ingest.py` 把 3 表**适配成**这 2 表，下游特征/模型/分配完全复用，引擎不重写。

### 4.0 对外 3 表输入（D3，列名支持中文/英文别名）

**① 客户表 `customers`**

| 字段 | 必填 | 说明 |
|------|------|------|
| `uid` | ✅ | 用户唯一标识 |
| `age`/`年龄` | ❌ | 年龄（数值特征） |
| `gender`/`性别` | ❌ | 性别（男/女/M/F → one-hot） |
| `city`/`城市` | ❌ | 城市 |
| `register_date`/`注册日期` | ❌ | 注册日期（算注册时长） |

**② 商品表 `products`**

| 字段 | 必填 | 说明 |
|------|------|------|
| `item_id`/`商品ID` | ✅ | 商品唯一标识 |
| `price`/`价格` | ✅ | 商品价格（下单金额由它得出） |
| `category`/`品类` | ❌ | 品类（品类偏好特征） |

**③ 行为日志 `behavior`**

| 字段 | 必填 | 说明 |
|------|------|------|
| `uid` | ✅ | 用户标识 |
| `behavior_type`/`行为类型` | ✅ | 枚举：浏览 / 加购 / 下单 / **领券** / **用券** |
| `item_id`/`商品ID` | △ | 浏览/加购/下单需填；领券/用券可空 |
| `behavior_time`/`行为时间` | ✅ | 行为时间 |
| `coupon_value`/`券面额` | △ | 领券/用券填（是 Uplift 的 treatment 维） |
| `coupon_id`/`券ID` | ❌ | 配对领券↔用券；缺省自动生成 |
| `amount`/`金额` | ❌ | 下单金额；缺省取商品价格 |

> **为什么必须有「领券/用券」**：Uplift 要回答"发券比不发券多带来多少购买"，必须有发券对照。
> 领券=treatment，领券后是否下单=outcome，用券→核销率特征。无券事件则退化为无法估计 uplift（见 ADR 9.6）。
>
> **3 表 → 2 表 适配（`data/ingest.py`）**：`下单`→`orders`（金额取自商品价格）；`领券/用券`→`coupons`（领券给 receive_time，用券回填 use_time/used，按 coupon_id 配对，缺省近似配对）；同时从客户属性 + 行为漏斗（浏览/加购数、加购率、交互均价）派生 `extra_features` 并入特征矩阵。

### 4.1 订单表 `orders.csv`（内部契约）
| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `user_id` | str | ✅ | 用户唯一标识（微信 OpenID 等脱敏后） |
| `order_id` | str | ✅ | 订单号 |
| `order_time` | datetime | ✅ | 下单时间 |
| `amount` | float | ✅ | 订单金额（元） |
| `category` | str | ❌ | 商品品类（做品类偏好特征） |

### 4.2 优惠券表 `coupons.csv`
| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `user_id` | str | ✅ | 用户唯一标识 |
| `coupon_id` | str | ✅ | 券 ID |
| `coupon_value` | float | ✅ | 券面额（元） |
| `receive_time` | datetime | ✅ | 领券时间 |
| `use_time` | datetime | ❌ | 用券时间（空=未核销） |
| `used` | int(0/1) | ❌ | 是否核销（缺省由 use_time 推断） |

> 真实场景里这两张表来自微信支付后台 / 小程序后台。初版用 `synth.py` 合成等价结构的数据。

### 4.3 内部派生「训练样本」
特征工程后，每个用户聚合成一行：`[user_id, f1...fn, treatment, outcome]`
- `treatment`：观察期内是否发过券（0/1）
- `outcome`：观察期后是否产生购买（0/1）
- Uplift 即估计 `P(outcome=1 | treat=1) - P(outcome=1 | treat=0)`

---

## 5. 各模块详细设计

### 5.1 config.py
集中所有可调参数（dataclass，带默认值，可被 env / API 覆盖）：
- `COUPON_VALUES = [5, 10, 20, 50]` 面额档位
- `TOTAL_BUDGET`、`N_USERS` 预算与人数
- `EXPECTED_REDEMPTION_RATE` 预期核销率
- 分组比例 `GROUP_RATIOS = {A:0.30, B:0.20, C:0.15, D:0.35}`（方案 10.2）
- `SURPRISE_FLOOR_WEIGHT` 每个面额最低权重（保证人人有机会抽到大额，方案 3.4）
- `LLM_ENABLED / LLM_MODEL / LLM_BASE_URL`（默认走 Anthropic Claude，可关闭）
- 观察期/转化期窗口天数

### 5.2 data/
- **loader.py**：`load_orders(path)` / `load_coupons(path)`，做列校验、类型转换、缺失值处理；`used` 缺失时由 `use_time` 非空推断。
- **synth.py**：`generate(n_users, seed)` 生成订单+优惠券。**关键：要植入真实可被模型学到的 uplift 结构**——按用户隐变量分四象限（Sure Thing / Persuadable / Lost Cause / Sleeping Dog），不同象限对券的真实响应不同，这样模型训练出来才有意义、A/B 才能看出差异。

### 5.3 features/rfm.py
按方案 2.7 节算 10-20 个特征（只用订单表+优惠券表）：
- Recency：最近购买/领券距今天数
- Frequency：近 30/60/90 天购买、领券、用券次数
- Monetary：近 N 天累计消费、平均客单价、最大/最小单笔
- 券行为：历史核销率、平均用券面额、券敏感度
- 用户属性：注册天数（由首单近似）、品类偏好 one-hot
输出 `feature_matrix(orders, coupons) -> DataFrame(index=user_id)`。

### 5.4 models/
- **base.py**：`UpliftModel` 抽象类，统一接口
  - `fit(X, treatment, outcome)`
  - `predict_uplift(X) -> np.ndarray`（单一 treatment 的 uplift）
  - `predict_uplift_by_value(X, values) -> DataFrame`（每面额一列 uplift，初版用面额作为 treatment 强度的简化建模）
- **two_model.py**：分别对 treat / control 组训练分类器（默认 `GradientBoostingClassifier`），uplift = 两者预测概率之差。简单、稳、无重依赖。
- **registry.py**：`get_model(name)` 工厂；初版注册 `"two_model"`，预留 `"dragonnet"`（方案指出 DragonNet 效果最优 +35%，作为下一阶段升级点，需 torch）。
- **evaluate.py（D6）**：uplift 因果评估。在 30% 留出测试集上用观测 treatment/outcome 算：分位 uplift 表（按预测降序分 10 档看真实 uplift，理想单调递减）、Qini 系数 / AUUC（单一分数，>0 优于随机）、子模型 AUC。`build_recommendations(evaluate=True)` 调用并把结果放进 `RecommendResult.evaluation`，对客 Web 结果页展示。注：小样本方差大（Qini 可能翻负），故评估设 `MIN_EVAL_SAMPLES=200`、demo 默认 4000 用户。

### 5.5 allocation/
- **budget.py**：全局预算约束求解（方案 3.4「双层优化」）
  - 输入：每用户×每面额 uplift、总预算 B、预期核销率、面额表
  - 约束：`Σ(面额 × 抽中概率 × 核销率) ≤ B`
  - 目标：最大化 `Σ uplift`
  - 初版实现：**贪心/按 uplift 性价比（uplift / 期望成本）排序分配**，先保证可跑通可解释；预留 `scipy.optimize.linprog` 的 LP 精确解作为升级。
- **surprise.py**：把每用户的「各面额 uplift」转成**抽奖奖池权重**（方案 3.4 惊喜券核心）
  - uplift 越高 → 权重越高，但每个面额保留 `SURPRISE_FLOOR_WEIGHT` 最低权重（人人有机会抽到大额，规避杀熟感）
  - 输出每用户一个面额概率分布 + 一次抽样结果（模拟用户「拆红包」）

### 5.6 experiment/abtest.py
- 按 `GROUP_RATIOS` 用 `hash(user_id)` 稳定分流到 A/B/C/D（方案 10.6：User ID Hash）
- 四组发券策略：A 不发 / B 随机面额 / C 规则（近30天未消费发10元）/ D uplift+惊喜券
- 用 synth 的真实响应机制模拟各组 outcome 与 GMV
- 计算方案 10.3 核心指标：增量 GMV、增量 ROI、节约率、核销率、人均券成本
- 显著性：`scipy.stats.ttest_ind`（GMV 均值差）、转化率比例检验；输出 p 值、置信区间

### 5.7 llm/copywriter.py
- `generate_coupon_copy(user_segment, coupon_value)` → 惊喜券文案（"🎉 恭喜抽到 XX 元红包！"）
- `explain_strategy(report_metrics)` → 给运营看的策略解释（方案 6.3 Step3「能在周会上汇报」的人话）
- 默认调 Claude（`claude-opus-4-8`，走 Anthropic API / .env key）；`LLM_ENABLED=false` 或无 key 时返回模板 mock 文案，**保证全流程永远能跑通**。

### 5.8 report/builder.py
- 汇总实验指标 + LLM 解释，生成方案 10.5 样式的**周报**（markdown / 终端文本）
- 含：本周概览、增量 GMV、增量 ROI、本周洞察（按面额/分群）

### 5.9 pipeline.py（编排）
```python
def run_pipeline(orders, coupons, config) -> PipelineResult:
    feats   = build_features(orders, coupons)
    samples = label_treatment_outcome(orders, coupons, feats, config)
    model   = get_model(config.model_name).fit(...)
    uplift  = model.predict_uplift_by_value(feats, config.coupon_values)
    alloc   = allocate_budget(uplift, config)
    weights = surprise_weights(uplift, config)
    exp     = run_abtest(orders, coupons, model, config)
    report  = build_report(exp, alloc, llm=copywriter)
    return PipelineResult(...)
```

### 5.10 api/main.py（FastAPI）
- `POST /score`：传用户特征 → 返回各面额 uplift
- `POST /allocate`：传用户列表 + 预算 → 返回每人惊喜券权重 & 抽样面额
- `GET /health`
- 在线推理加载离线训练好的模型文件（`model.joblib`）
- **对客 Web（D2 新增）**：
  - `GET /` 托管 `web/` 静态页（苹果风单页）
  - `POST /api/recommend`：multipart 上传 `orders` + `coupons`（可选 `budget`）→ **当场在上传数据上训练并跑 pipeline** → 返回 JSON：汇总指标 + 预览前若干行 + 完整结果的 CSV 文本与 xlsx(base64)。**全程内存处理、不落盘**。
  - `GET /api/demo`：用 `synth.generate` 即时造一份数据跑通，给没有数据的访客体验。
  - 与 `/score`、`/allocate` 的区别：后者用**离线预训练模型**做在线推理；`/api/recommend` 用**用户上传的数据现训现算**，是对客主路径。

### 5.11 app/dashboard.py（Streamlit）
上传 orders.csv + coupons.csv → 跑 pipeline → 展示周报、uplift 四象限分布、各组对比柱状图 → 下载预测结果 CSV。无数据时一键「用样例数据」。

### 5.12 web/（对客网站前端，D2 新增）
苹果风纯静态单页（无构建步骤），面向商家/访客：
- 交互三态：**上传**（两个拖拽上传位：订单数据 / 历史发券数据，可调预算，或点「用示例数据体验」）→ **计算中**（loading）→ **结果**（汇总卡片：覆盖客户数/建议发券人数/预算用量/预期增量；结果预览表；CSV/Excel 下载按钮）。
- 输出表（对客，中文列）：`客户ID / 推荐券面额 / 是否发放 / 最优面额 / 预期增量购买概率 / 预期成本`。其中"推荐券面额"为预算约束下实际建议发放的面额（不建议发则为 0），"最优面额"为不考虑预算时 uplift 最大的面额。
- 设计语言：`-apple-system` 系统字体、大留白、单一主色、圆角 + 轻投影、克制动效。
- 下载实现：前端把后端回传的 CSV 文本 / xlsx(base64) 包成 Blob 触发下载，无需服务端存储。

---

## 6. 技术选型

| 用途 | 选型 | 理由 |
|------|------|------|
| 语言 | Python 3.10+ | 方案指定，数据科学生态 |
| 数据处理 | pandas, numpy | 标准 |
| 模型 | scikit-learn（初版） | Two-Model 够用、无重依赖；DragonNet(torch) 留作升级 |
| 统计 | scipy.stats | t 检验、比例检验 |
| API | FastAPI + uvicorn | 轻量、自带文档 |
| 前端 | Streamlit | 方案指定，几百行出一个可交互页面 |
| LLM | Anthropic Claude（claude-opus-4-8），可 mock | 文案/解释；默认最新模型，可关闭 |
| 模型持久化 | joblib | sklearn 标配 |
| 测试 | pytest | - |
| 部署 | Docker + docker-compose | 单服务一键起 |

---

## 7. 里程碑与状态

> 状态：⬜ 未开始 / 🟡 进行中 / ✅ 完成。与任务列表同步。

| # | 里程碑 | 状态 |
|---|--------|------|
| M0 | 项目骨架 + plan/demand/debug.md | ✅ |
| M1 | 数据层（loader + synth）可生成样例数据 | ✅ |
| M2 | 特征层 RFM | ✅ |
| M3 | 模型层 Two-Model uplift 可训练可预测 | ✅ |
| M4 | 分配层 预算约束 + 惊喜券权重 | ✅ |
| M5 | 实验层 A/B/C/D 模拟 + 显著性 | ✅ |
| M6 | LLM 文案 + 周报 | ✅ |
| M7 | pipeline 编排 + CLI 跑通 | ✅ |
| M8 | FastAPI + Streamlit | ✅ |
| M9 | 测试 + Docker 打包 + 端到端验证 | ✅ |
| M10 | 对客 Web 网站（苹果风）：上传数据 → 下载每客户推荐券面额（D2） | ✅ |
| M11 | 改用「客户/商品/行为日志」3 表输入，适配层 + 新特征 + 跑通（D3） | ✅ |
| M12 | uplift 模型评估（Qini/AUUC/分位uplift）+ 页面展示（D6） | ✅ |

> **初版已跑通（2026-06-05）**：`pytest` 15 项全绿；CLI 端到端跑出周报，D 组（智能发券）
> 增量 GMV ¥9,615、ROI 1.65、**统计显著（p≈0.0014）**，且较随机发券节约 18% 券成本；
> FastAPI `/score`、`/allocate` 经 TestClient 验证可用。实测验证了核心假设——「模型能省钱」。

**初版「跑通」的验收标准：**
1. `python scripts/gen_sample_data.py` 生成样例 CSV。
2. `python scripts/run_pipeline.py` 用样例数据端到端跑出一份周报，且 D 组（智能发券）增量 ROI 显著优于 B/C 组（验证模型有效）。
3. `pytest` 全绿。
4. `streamlit run app/dashboard.py` 能上传 CSV 看报告。
5. `docker compose up` 一键起 API + 面板。

---

## 8. 后续阶段（不在初版，登记备查）

- **模型升级**：接入 DragonNet（方案实测 +35.17%，最优）、EFIN；Qini/AUUC 评估曲线。
- **预算优化升级**：LP 精确解（scipy.optimize.linprog）替代贪心。
- **轻量版**：PostHog 埋点接入、LiteLLM 网关、Metabase 报表、惊喜券前端 SDK（小程序拆红包）。
- **完整版**：Tracardi CDP + GrowthBook 实验平台 + Dify Agent；多租户、行业模板（餐饮/电商/教育）。
- **多臂老虎机**：动态流量分配自动优化策略。

---

## 9. 关键设计决策记录（ADR 摘要）

1. **初版只做极简版**：优先验证「模型能省钱」这个核心假设，而非堆平台。
2. **合成数据内置真实 uplift 结构**：否则模型学不到东西、A/B 看不出差异，demo 没有说服力。
3. **LLM 必须可关闭**：没有 API key 也要能跑通全流程，降低任何人上手门槛。
4. **面额作为 treatment**：初版把「发多少券」简化为对每个候选面额各算一次 uplift，而非连续剂量响应模型——简单、可解释，后续可升级为剂量响应。
5. **惊喜券保底权重**：每个面额都有最低中奖权重，是「规避大数据杀熟」的产品级护栏，不是可选项。
6. **3 表输入用适配层而非重写引擎（D3）**：对外换成「客户/商品/行为日志」3 表，但通过 `data/ingest.py` 适配成内部 orders+coupons，引擎核心零改动。「券」这一维通过在行为日志加『领券/用券』行为类型承载——没有它就无法估计 uplift，所以它是 3 表方案的必备项，不是可选。

---

## 变更日志

- **2026-06-05**：初始化。确定初版做极简版 MVP，定义架构、目录、数据契约、9 个里程碑。（by Claude）
- **2026-06-05**：初版 M0-M9 全部完成并跑通。新增决策 9.4（面额作为 treatment 特征喂入处理模型）、9.5（惊喜券保底权重）。实测结果见里程碑表下方说明。（by Claude）
- **2026-06-06**：受理需求 D2——对客苹果风 Web 网站。新增入口层 `web/` 与 `POST /api/recommend`、`GET /api/demo`（内存直传直回，第一版不需任何云存储）；`pipeline.py` 新增推荐表构建函数；新增依赖 python-multipart、openpyxl。架构图/目录/5.10-5.12/里程碑 M10 同步更新。（by Claude）
- **2026-06-07**：受理需求 D6——uplift 模型评估。新增 `models/evaluate.py`（Qini/AUUC/分位uplift/子模型AUC，因果评估，留出测试集）；`build_recommendations` 增 evaluate 选项并入 `RecommendResult.evaluation`；Web 结果页新增「模型评估」卡片（含分位 uplift 柱）；trace_run 增评估节。记录：小样本评估方差大，demo 默认用户数提到 4000。里程碑 M12。（by Claude）
- **2026-06-06**：受理需求 D5——新增全链路调试追踪脚本 `scripts/trace_run.py`，把示例数据输入→输出每步中间结果（含 uplift 模型内部：对照概率/各面额处理概率/差值）写入 `sample_run_trace.md`。记录：小样本下 uplift 噪声大，调试/演示建议 ≥3000 用户。（by Claude）
- **2026-06-06**：受理需求 D4——Windows 运行手册 `RUN_ON_WINDOWS.md` + `start_windows.bat`；debug.md 补录 B1（.gitignore 误伤 data 包）。（by Claude）
- **2026-06-06**：受理需求 D3——对外输入改为「客户/商品/行为日志」3 表。新增数据契约 4.0、适配层 `data/ingest.py`、3 表合成器 `data/synth_tables.py`、`pipeline.recommend_from_tables`、特征 extra_features 通道；Web/`/api/recommend`/`/api/demo` 切到 3 表（3 上传位）。决策 9.6（适配层不重写引擎、领券/用券承载 treatment）。里程碑 M11。（by Claude）
