# test.md — 测试记录

> 本项目所有测试的清单、目的、断言、与历次运行结果都记录在这里。
> 每次跑测试（尤其是新增/修改用例、或修完 bug 回归）后，**把结果追加到「运行记录」**。
> 目的：任何新接手的人/AI 不用自己跑，就能知道项目测了什么、当前是否健康。
>
> 配套：`plan.md`（架构）· `demand.md`（需求）· `debug.md`（踩坑）。

---

## 1. 怎么跑

```bash
pip install -e .            # 首次需安装（src 布局）
pytest                      # 全部
pytest -v                  # 看每个用例名
pytest -q                  # 安静模式
pytest tests/test_model_allocation.py   # 单文件
pytest -k "experiment"                   # 按关键字
```

- 测试框架：**pytest**（配置在 `pyproject.toml`：`pythonpath=["src"]`、`testpaths=["tests"]`）。
- **不依赖真实数据**：`tests/conftest.py` 在 session 级即时生成 2000 用户的小规模合成数据并训练一个模型，所有用例复用，跑得快。
- **不依赖 LLM key**：未配置时自动走模板文案，相关用例专门校验这一降级路径。

---

## 2. 公共 Fixtures（`tests/conftest.py`）

| fixture | 作用域 | 内容 |
|---------|--------|------|
| `config` | session | `Config(total_budget=30000)` 测试用配置 |
| `synth` | session | 2000 用户合成数据（orders/coupons/truth） |
| `training` | session | 由 synth 派生的训练样本（特征+treatment+outcome） |
| `model` | session | 在 training 上 fit 好的 Two-Model uplift |

---

## 3. 测试清单（15 项）

### 3.1 数据层 + 特征层 — `tests/test_data_features.py`（6 项）

| 用例 | 验证什么 | 关键断言 |
|------|---------|---------|
| `test_synth_schema` | 合成数据字段符合数据契约 | orders/coupons 含所有必填列且非空 |
| `test_loader_validates_missing_columns` | 加载器对缺列会报错 | 缺列时抛 `DataValidationError` |
| `test_loader_roundtrip` | 加载后数据规整正确 | amount 全 > 0；used ∈ {0,1} |
| `test_ground_truth_uplift_signs` | 四象限地面真值方向正确 | persuadable uplift>0、sleeping_dog<0；面额↑则 uplift↑（边际递减） |
| `test_purchase_prob_bounds` | 购买概率在合法区间 | 0 ≤ p ≤ 1 |
| `test_training_frame` | 训练样本结构与信号正确 | 长度一致、标签∈{0,1}、**存在正的平均处理效应 ATE>0** |

### 3.2 模型层 + 分配层 — `tests/test_model_allocation.py`（5 项）

| 用例 | 验证什么 | 关键断言 |
|------|---------|---------|
| `test_model_learns_heterogeneity` | 模型学到个体异质性 | best_uplift：**persuadable > sleeping_dog 且 > lost_cause** |
| `test_uplift_by_value_shape` | 每面额一列 uplift | 列=面额档位、行数=用户数 |
| `test_budget_respects_constraint` | 预算约束生效 | **total_cost ≤ budget**；被选中用户 uplift 全为正 |
| `test_surprise_weights_floor_and_sum` | 惊喜券权重合法 | 每个面额权重 **≥ 保底 floor**；每行权重和 = 1 |
| `test_draw_in_values` | 抽奖结果合法 | 抽中面额 ∈ 配置档位 |

### 3.3 实验层 + 编排层 — `tests/test_experiment_pipeline.py`（4 项）

| 用例 | 验证什么 | 关键断言 |
|------|---------|---------|
| `test_assign_groups_stable_and_proportional` | 分流稳定且比例正确 | 两次分流结果一致；D 组占比 ≈ 配置比例（误差<5%） |
| `test_experiment_smart_beats_random` | 智能发券优于随机 | 四组齐全；**D 组增量 GMV ≥ B 组**；D 相比随机有正成本节约 |
| `test_llm_mock_fallback_always_works` | LLM 不阻塞流程 | 未启用时 `active=False`，文案/解释仍非空 |
| `test_pipeline_end_to_end` | 端到端跑通 | 产出 experiment 非空、报告含标题、抽奖结果长度对齐 |

### 3.4 三表输入：摄取/适配/推荐 — `tests/test_ingest_tables.py`（5 项，D3）

| 用例 | 验证什么 | 关键断言 |
|------|---------|---------|
| `test_generate_tables_schema` | 3 表合成结构正确 | 客户/商品/行为列齐全；行为类型含 **浏览/下单/领券/用券** |
| `test_to_internal_adapter` | 3 表 → 内部 2 表适配 | 下单→orders（金额>0）、领券/用券→coupons（**有核销**）、派生 x_ 特征 |
| `test_recommend_from_tables` | 3 表端到端推荐 | 输出列正确；**预期券成本 ≤ 预算** |
| `test_chinese_column_aliases` | 中文列名可识别 | 1 下单→1 订单、2 领券→2 券、**1 用券被配对核销** |
| `test_no_coupon_raises` | 无领券/用券应拦截 | 抛 `DataValidationError`（无法估计 uplift） |

### 3.5 Uplift 模型评估 — `tests/test_evaluate.py`（5 项，D6）

| 用例 | 验证什么 | 关键断言 |
|------|---------|---------|
| `test_qini_positive_for_good_ranking` | 好排序得正 Qini | Qini系数>0、AUUC>0 |
| `test_qini_near_zero_for_random_ranking` | 乱排序更差 | 好排序 Qini > 打乱后 Qini |
| `test_quantile_table_shape_and_fields` | 分位表结构 | 10 档、字段齐；**第1档实际uplift ≥ 末档** |
| `test_evaluation_attached_and_available` | 评估接入推荐结果 | `RecommendResult.evaluation.可用=True`，含 Qini/AUUC/分位表/样本/提升倍数；AUC∈[0,1] |
| `test_evaluation_unavailable_on_tiny_data` | 小样本优雅降级 | 样本不足时 `可用=False`（不报错） |

> 这三组「关键断言」就是项目的**正确性定义**——它们守护了核心商业假设：
> 「合成数据里有真实 uplift → 模型能学到 → 预算花在对的人身上 → A/B 证明 D 最优」。

---

## 4. 覆盖范围与缺口

**已覆盖**：数据校验、合成数据正确性、特征/标签、模型异质性、预算约束、惊喜券保底、分流、A/B 指标方向、LLM 降级、端到端。

**暂未覆盖**（后续补，登记备查）：
- FastAPI 接口的自动化用例（目前靠 TestClient 手动冒烟，见运行记录 R1）。
- Streamlit 面板（目前靠 `py_compile` + 手动启动验证）。
- ~~模型评估指标（Qini/AUUC）~~ ✅ 已在 D6 加入（`test_evaluate.py`）。
- 极端/脏数据（空表、全未核销、单一用户）的边界用例。

---

## 5. 运行记录（按时间倒序）

### R4 — 2026-06-07 · 新增 uplift 模型评估（D6）后回归
- **变更点**：新增 `models/evaluate.py`（Qini/AUUC/分位uplift/子模型AUC）、`tests/test_evaluate.py`；`build_recommendations` 增 evaluate 选项；Web 结果页加「模型评估」卡片；trace_run 增评估节。
- **pytest**：`python -m pytest -q` → **25 passed in ~12s**（20 + 5 新），0 失败。
- **修的坑**：① numpy 2.x 移除 `np.trapz` → 改手写梯形积分；② `np.array_split` 把 DataFrame 转成 ndarray 致字符串索引报错 → 改对行号分组再 iloc。
- **冒烟**：3000~5000 用户下评估稳定（Qini>0、Top档提升 1.8~4.5×、子模型 AUC≈0.72~0.78）；2500 以下偶现 Qini 翻负 → demo 默认改 4000。TestClient `/api/demo` 返回 `evaluation`；真实 uvicorn 页面含 `eval-card/eval-metrics/eval-deciles`。
- **结论**：评估指标正确接入并展示，未破坏既有功能。

### R3 — 2026-06-06 · 改用 3 表输入（D3）后回归
- **变更点**：新增 `data/ingest.py`（3 表校验+适配）、`data/synth_tables.py`（3 表合成）、`pipeline.recommend_from_tables`、特征 extra_features 通道；Web/`/api/recommend`/`/api/demo` 切到 3 表输入。
- **pytest**：`python -m pytest -q` → **20 passed in ~5.5s**（15 旧 + 5 新 `test_ingest_tables.py`），0 失败。
- **新功能冒烟（手动）**：
  - `generate_tables`(1200 用户)→ behavior 含 浏览/加购/下单/领券/用券；`to_internal` 出 orders+coupons（核销率≈0.27）+ 8 个 x_ 特征；`recommend_from_tables` 出推荐表，预算约束生效。
  - TestClient：`GET /api/demo`（3 表合成）→200；`POST /api/recommend`（上传 customers/products/behavior 三 CSV）→200 出 1974 行；缺列→400；**无领券/用券→400 且提示"无法估计 uplift"**。
  - 真实 uvicorn（:8766）：`/`（含 3 个上传位 drop-customers/products/behavior）、`/app.js`、`/api/demo` 全 200。
- **结论**：3 表输入端到端可用，券维由「领券/用券」承载，未破坏既有功能。

### R2 — 2026-06-06 · 新增对客 Web（D2）后回归
- **变更点**：新增 `web/`（苹果风前端）、`POST /api/recommend`、`GET /api/demo`、静态托管，`pipeline.build_recommendations`；新增依赖 python-multipart、openpyxl。
- **pytest 回归**：`python -m pytest -q` → **15 passed in 3.56s**，0 失败（既有用例未受影响）。
- **新功能冒烟（手动，尚未自动化）**：
  - `build_recommendations`（800 合成用户）：产出 789 行推荐表，列＝客户ID/推荐券面额/是否发放/最优面额/预期增量购买概率/预期成本，汇总指标齐全。
  - TestClient：`GET /`→200(html)、`GET /api/demo`→200（返回 csv+xlsx，xlsx 可被 openpyxl 打开且表头正确）、`POST /api/recommend`（上传两 CSV）→200、坏数据（缺列）→**400 且报错信息友好**。
  - 真实 uvicorn（:8765）：`/`、`/styles.css`、`/app.js`、`/api/demo`、`/health` 全部 200。
- **结论**：对客 Web 主路径端到端可用，未破坏既有功能。
- **待补**：把 `/api/recommend`、`/api/demo`、坏数据 400 写成 pytest 自动化用例（见 §4 缺口）。

### R1 — 2026-06-06 · 初版全量通过
- **命令**：`pytest -v`
- **环境**：Python 3.11.6，pytest 9.0.3，platform linux
- **结果**：**15 passed in 4.13s**，0 失败 / 0 跳过。
- 明细：
  ```
  test_data_features.py ......... 6 passed
  test_model_allocation.py ...... 5 passed
  test_experiment_pipeline.py ... 4 passed
  ```
- **附：端到端冒烟（非 pytest）**
  - `python scripts/run_pipeline.py` → 跑出周报，D 组增量 GMV ¥9,615、ROI 1.65、**p≈0.0014 显著**，较随机发券节约 18% 券成本。
  - FastAPI（TestClient）：`/health` ok、`/info` 返回 26 特征、`/score` 与 `/allocate` 正常返回。
  - `py_compile` 全部源文件通过。
- **结论**：初版健康，核心假设被测试与实测共同验证。

<!-- 新的运行记录追加到这里（保持倒序，最新在上）：
### R2 — YYYY-MM-DD · 简述
- 命令 / 环境 / 结果 / 变更点
-->
