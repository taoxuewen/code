# plan.md — 智能发券引擎 落地实现规划

> 本文件是**整个项目的活地图**。任何新加入的人（或 AI）只读这一份，就能理解：我们在做什么、为什么这么做、代码长什么样、下一步往哪走。
> 规划一旦有变动，**必须同步更新本文件**（见末尾「变更日志」）。
>
> 配套文件：
> - `demand.md` — 需求记录（用户每次提的需求 + 讨论结论）
> - `debug.md` — bug 记录（每次报错 → 定位 → 修复）
> - `test.md` — 测试记录（所有用例清单 + 历次运行结果）
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
│   │   ├── loader.py         # 读取+校验订单/优惠券 CSV
│   │   └── synth.py          # 合成数据生成器（含真实 uplift 机制）
│   ├── features/
│   │   └── rfm.py            # RFM + 券行为特征
│   ├── models/
│   │   ├── base.py           # UpliftModel 抽象基类
│   │   ├── two_model.py      # 双模型 uplift（默认）
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
├── app/dashboard.py          # Streamlit
├── scripts/
│   ├── gen_sample_data.py    # 生成 data/sample
│   └── run_pipeline.py       # CLI 跑全流程
└── tests/                    # pytest
```

---

## 4. 数据契约（最重要的对齐点）

初版只要求商家提供两张 CSV。**字段命名是整个项目的接口**，改动需谨慎。

### 4.1 订单表 `orders.csv`
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

### 5.11 app/dashboard.py（Streamlit）
上传 orders.csv + coupons.csv → 跑 pipeline → 展示周报、uplift 四象限分布、各组对比柱状图 → 下载预测结果 CSV。无数据时一键「用样例数据」。

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

---

## 变更日志

- **2026-06-05**：初始化。确定初版做极简版 MVP，定义架构、目录、数据契约、9 个里程碑。（by Claude）
- **2026-06-05**：初版 M0-M9 全部完成并跑通。新增决策 9.4（面额作为 treatment 特征喂入处理模型）、9.5（惊喜券保底权重）。实测结果见里程碑表下方说明。（by Claude）
