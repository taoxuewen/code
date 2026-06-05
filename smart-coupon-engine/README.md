# 智能发券引擎（Smart Coupon Engine）— 极简版 MVP

用 **Uplift 因果模型** 算清楚「这个用户该不该发券、发多少券」，用 **惊喜券** 抽奖外壳规避大数据杀熟，并用 **A/B 实验** 证明省了多少钱。

> **我们卖的不是软件，是「省下来的券成本」。**
>
> 商业 + 技术方案原文：`../tracardi-growthbook-dify-智能营销引擎方案.md`
> 项目活文档（新接手请先读）：**[plan.md](plan.md)** 架构与规划 · **[demand.md](demand.md)** 需求 · **[debug.md](debug.md)** 踩坑记录

---

## 目录

- [它解决什么问题](#它解决什么问题)
- [核心闭环](#核心闭环)
- [快速开始（5 步跑通）](#快速开始5-步跑通)
- [怎么测试](#怎么测试)
- [怎么运行（三种方式）](#怎么运行三种方式)
- [各部分代表什么](#各部分代表什么)
- [数据格式](#数据格式)
- [实测结果](#实测结果跑样例数据)
- [配置项](#配置项)
- [后续路线](#后续路线)

---

## 它解决什么问题

中小私域商家发券的两难：**滥发券亏钱**（发给本来就会买的人）vs **不发券丢单**。
传统响应模型只会预测「谁会买」，区分不了「因为券才买」和「不发券也会买」。

本项目用 **Uplift（增量）建模**，只对 **Persuadable（发券才买）** 的人发券，避开：
- **Sure Thing**（不发也买）— 发了白亏
- **Lost Cause**（发了也不买）— 发了浪费
- **Sleeping Dog**（发了反而烦）— 发了有害

再用「惊喜券」抽奖把个性化面额包装成「运气差异」，规避「为什么他 10 块我 5 块」的杀熟公关危机。

## 核心闭环

```
商家 CSV（订单表 + 优惠券表）
   → RFM 特征工程（26 个特征，只用这两张表）
   → Uplift 模型（每个用户 × 每个面额的增量分数）
   → 预算约束分配 + 惊喜券抽奖权重
   → A/B 模拟（A不发 / B随机 / C规则 / D智能 四组）+ 显著性检验
   → LLM 生成券文案 & 策略解释（无 key 自动降级模板）
   → 输出「能在周会上汇报」的周报
```

---

## 快速开始（5 步跑通）

```bash
cd smart-coupon-engine

# 1) 安装（建议先建虚拟环境 python -m venv .venv && source .venv/bin/activate）
pip install -e .

# 2) 生成样例数据（无需任何真实数据即可体验；默认 5000 用户）
python scripts/gen_sample_data.py
#   → 生成 data/sample/orders.csv、coupons.csv

# 3) 端到端跑一遍，打印周报 + 保存模型 model.joblib
python scripts/run_pipeline.py

# 4) 跑测试，确认一切正常
pytest -q

# 5) 启动交互面板（浏览器打开 http://localhost:8501）
streamlit run app/dashboard.py
```

> 不配置 LLM 也能完整跑通（文案/解释自动用模板）。要启用真实 Claude 文案：
> `cp .env.example .env`，把 `LLM_ENABLED=true` 并填 `ANTHROPIC_API_KEY`。

---

## 怎么测试

测试用 **pytest**，覆盖数据 / 特征 / 模型 / 分配 / 实验 / pipeline 六层，**不依赖真实数据**（fixture 内部即时生成小规模合成数据）。

```bash
pytest                 # 跑全部
pytest -q              # 安静模式
pytest -v              # 看每个用例名
pytest tests/test_model_allocation.py            # 只跑某个文件
pytest -k "experiment"                            # 按关键字筛选
```

测试文件与职责：

| 文件 | 测什么 |
|------|--------|
| `tests/conftest.py` | 公共 fixture：合成数据 + 训练好的模型（session 级，跑一次复用） |
| `tests/test_data_features.py` | CSV 校验、合成数据 schema、地面真值 uplift 正负号、训练样本存在正 ATE |
| `tests/test_model_allocation.py` | 模型学到异质性（persuadable > sleeping_dog）、预算不超支、惊喜券保底权重 & 概率和=1 |
| `tests/test_experiment_pipeline.py` | 分组稳定且比例正确、D 组增量 GMV 最高、LLM mock 永不阻塞、端到端 pipeline |

**关键断言**（这些就是项目的「正确性定义」）：
- 合成数据里 `treatment=1` 比 `treatment=0` 的转化率更高（植入了真实 uplift）。
- 模型预测的 best_uplift：`persuadable > sleeping_dog` 且 `> lost_cause`。
- 分配后 `total_cost ≤ budget`，选中的用户 uplift 全为正。
- 惊喜券每个面额权重 `≥ floor`、每行权重和 `= 1`。
- A/B 模拟里 D 组增量 GMV ≥ B 组，且相比随机发券有正的成本节约。

---

## 怎么运行（三种方式）

### 方式 1：命令行批量跑（离线，最常用）

```bash
# 用样例数据（含 A/B 模拟与显著性，因为有真值标签）
python scripts/run_pipeline.py

# 用你自己的真实数据（无真值 → 只做特征/模型/分配，不做 A/B 模拟）
python scripts/run_pipeline.py path/to/orders.csv path/to/coupons.csv
```
输出：终端打印周报 markdown，并把训练好的模型存为 `model.joblib`（供 API 加载）。

### 方式 2：在线推理 API（FastAPI）

```bash
uvicorn coupon_engine.api.main:app --reload
# 打开交互文档 http://localhost:8000/docs
```

| 接口 | 方法 | 作用 |
|------|------|------|
| `/health` | GET | 健康检查 + 模型是否就绪 |
| `/info` | GET | 模型名、特征列、面额档位 |
| `/score` | POST | 传用户特征 → 返回每个面额的 uplift + 最优面额 |
| `/allocate` | POST | 传用户特征 → 返回惊喜券奖池权重 + 抽中面额 |

示例：
```bash
curl -X POST http://localhost:8000/score \
  -H "Content-Type: application/json" \
  -d '{"users":[{"recency_order_days":80,"freq_order_30":0,"hist_redemption_rate":0.6}]}'
```
> API 启动需要先有 `model.joblib`（先跑一次 `scripts/run_pipeline.py`）。

### 方式 3：Streamlit 面板（给运营/客户看）

```bash
streamlit run app/dashboard.py
```
上传 orders.csv + coupons.csv（或点「用样例数据跑一遍」）→ 看周报、uplift 分布、四组对比柱状图 → 下载发券决策 CSV。

### 方式 4：Docker 一键起 API + 面板

```bash
docker compose up        # API → :8000，面板 → :8501
```

---

## 各部分代表什么

```
smart-coupon-engine/
├── plan.md / demand.md / debug.md   # 三份活文档（架构 / 需求 / 踩坑）
├── README.md                        # 本文件
├── pyproject.toml / requirements.txt# 包与依赖（src 布局）
├── Dockerfile / docker-compose.yml  # 容器化（API + 面板）
├── .env.example                     # LLM 配置样例（复制为 .env）
│
├── data/sample/                     # 合成样例 CSV（gen 脚本生成，已 gitignore）
│
├── src/coupon_engine/               # 核心包，按「层」组织，每层只依赖下层
│   ├── config.py                    # ▶ 全局配置：面额档位/预算/分组比例/LLM 开关…
│   ├── data/
│   │   ├── loader.py                # ▶ 读取+校验订单/优惠券 CSV（数据契约守门）
│   │   └── synth.py                 # ▶ 合成数据生成器 + 地面真值响应函数
│   │                                #    （内置 Uplift 四象限，让模型有东西可学）
│   ├── features/rfm.py              # ▶ RFM + 券行为特征；派生 treatment/outcome 标签
│   ├── models/
│   │   ├── base.py                  # ▶ UpliftModel 抽象接口（便于换更强的模型）
│   │   ├── two_model.py             # ▶ 双模型 Uplift（默认实现，sklearn）
│   │   └── registry.py             # ▶ 模型注册/工厂（预留 DragonNet 升级位）
│   ├── allocation/
│   │   ├── budget.py                # ▶ 预算约束下贪心最大化 uplift（决定发给谁）
│   │   └── surprise.py             # ▶ uplift→抽奖权重 + 保底（惊喜券，规避杀熟）
│   ├── experiment/abtest.py         # ▶ A/B/C/D 分流模拟 + 增量GMV/ROI/节约率 + 显著性
│   ├── llm/copywriter.py            # ▶ 券文案/策略解释（无 key 自动降级模板）
│   ├── report/builder.py            # ▶ 把指标+解释拼成周报 markdown
│   ├── pipeline.py                  # ▶ 编排层：把上面各层串成端到端流程
│   └── api/main.py                  # ▶ FastAPI 在线推理服务
│
├── app/dashboard.py                 # ▶ Streamlit 交互面板
├── scripts/
│   ├── gen_sample_data.py           # ▶ 生成 data/sample 样例数据
│   └── run_pipeline.py             # ▶ CLI 跑全流程
└── tests/                           # ▶ pytest 六层测试
```

**数据流（一句话）**：`loader/synth` 出两张表 → `rfm` 出特征和标签 → `two_model` 出每面额 uplift → `budget/surprise` 决定发谁、抽到多少 → `abtest` 证明效果 → `copywriter/report` 出周报；`pipeline` 把它们串起来，`api/dashboard` 是两个入口。

---

## 数据格式

只需两张 CSV（字段详见 [plan.md 第 4 节](plan.md)）：

**orders.csv**（订单表）
| 字段 | 必填 | 说明 |
|------|------|------|
| `user_id` | ✅ | 用户标识（脱敏） |
| `order_id` | ✅ | 订单号 |
| `order_time` | ✅ | 下单时间 |
| `amount` | ✅ | 金额（元） |
| `category` | ❌ | 品类 |

**coupons.csv**（优惠券表）
| 字段 | 必填 | 说明 |
|------|------|------|
| `user_id` | ✅ | 用户标识 |
| `coupon_id` | ✅ | 券 ID |
| `coupon_value` | ✅ | 面额（元） |
| `receive_time` | ✅ | 领券时间 |
| `use_time` | ❌ | 用券时间（空=未核销） |
| `used` | ❌ | 是否核销（缺省由 use_time 推断） |

> 这两张表任何有微信支付后台的商家都有——这是「低门槛接入」的关键。

---

## 实测结果（跑样例数据）

`python scripts/run_pipeline.py` 在 5000 用户合成数据上的典型输出：

| 组 | 策略 | 增量 GMV | 增量 ROI | 统计显著 |
|----|------|---------|---------|---------|
| A | 不发券（对照） | — | — | — |
| B | 随机发券 | ¥2,605 | 0.65（白花钱） | ✗ |
| C | 规则发券 | ¥2,423 | 7.13（量小） | ✗ |
| **D** | **智能发券（Uplift+惊喜券）** | **¥9,615** | **1.65** | **✅ p≈0.0014** |

D 组相比随机发券 **节约 18% 券成本**，且是唯一统计显著的方案——这就是给商家看的「一笔账」。

---

## 配置项

集中在 `src/coupon_engine/config.py`（`Config` dataclass），可在代码里覆盖，或通过环境变量控制 LLM：

| 配置 | 默认 | 含义 |
|------|------|------|
| `coupon_values` | `[5,10,20,50]` | 券面额档位 |
| `total_budget` | `60000` | 本轮发券总预算 |
| `expected_redemption_rate` | `0.5` | 预期核销率（估成本用） |
| `group_ratios` | A30/B20/C15/D35 | A/B 分组比例 |
| `surprise_floor_weight` | `0.05` | 惊喜券每面额保底权重（防杀熟护栏） |
| `model_name` | `two_model` | 使用的 uplift 模型 |
| `llm_enabled` | `false` | 是否启用真实 LLM（环境变量 `LLM_ENABLED`） |

---

## 后续路线

详见 [plan.md 第 8 节](plan.md)：

- **模型升级**：DragonNet（方案实测最优 +35%）、Qini/AUUC 评估曲线
- **预算优化**：LP 精确解替代贪心
- **轻量版**：PostHog 埋点 + LiteLLM 网关 + Metabase 报表 + 小程序拆红包 SDK
- **完整版**：Tracardi CDP + GrowthBook 实验平台 + Dify Agent，多租户 + 行业模板

---

## 许可证 / 维护

本项目实现的是开源底座方案的极简版 MVP。三份活文档（plan/demand/debug）随开发持续更新——**改代码也要改文档**。
