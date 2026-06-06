# RUN_ON_WINDOWS.md — 在 Windows 上运行本项目（人 / AI 都能照着执行）

> **如果你是一个 AI 助手在读这份文件**：请把下面「执行步骤」从上到下依次执行。
> 每一步都给了可直接复制运行的命令。**只要某一步报错，先去看第 6 节「常见问题速查」**；
> 若仍解决不了，或你做了任何修复，**务必把这次 bug 按格式记录进 [debug.md](debug.md)**（见第 7 节，这是硬性要求）。
>
> 这个项目是一个「智能发券引擎」：上传 客户/商品/行为日志 三张 CSV，
> 算出每位客户该发多少优惠券面额，结果可下载为 CSV/Excel。
> 架构与思路详见 [plan.md](plan.md)，需求历史见 [demand.md](demand.md)，测试见 [test.md](test.md)。

---

## 0. 适用环境与结论

- ✅ **Windows 10 / 11 完全可以运行，不需要 Mac。**「苹果风」只是网页的视觉风格（CSS），与操作系统无关。
- 全程**纯本地、零云成本**：上传的数据只在内存计算、不落盘、不上传任何服务器。
- 命令在 **PowerShell** 或 **CMD（命令提示符）** 里都能跑。下面以 PowerShell 为主，差异处会标注。

---

## 1. 前置：安装 Python 3.10+

1. 打开终端，先检查是否已装：
   ```powershell
   python --version
   ```
   - 显示 `Python 3.10.x` ~ `3.12.x` → ✅ 跳到第 2 节。
   - 提示「不是内部或外部命令」或弹出应用商店 → 需要安装。
2. 安装：去 <https://www.python.org/downloads/> 下载 Windows 安装包。
   **安装第一屏务必勾选 ☑ "Add python.exe to PATH"**，再点 Install Now。
3. 装完**关掉并重新打开终端**，再次 `python --version` 确认。

> 备注：若 `python` 不行但 `py` 可以，下文所有 `python` 都可换成 `py`。

---

## 2. 获取代码

二选一：

**方式 A：用 Git（推荐，方便以后 `git pull` 更新）**
```powershell
cd $HOME\Documents
git clone https://github.com/taoxuewen/code.git
cd code\smart-coupon-engine
```

**方式 B：不想装 Git → 下载 ZIP**
1. 打开 <https://github.com/taoxuewen/code>
2. 点绿色 **Code** 按钮 → **Download ZIP** → 解压
3. 进入解压出来的 `code\smart-coupon-engine` 目录，在该目录地址栏输入 `powershell` 回车，即可在此目录打开终端。

> ⚠️ 后面所有命令都假设你的**当前目录在 `smart-coupon-engine`**（里面能看到 `pyproject.toml`、`src`、`web` 文件夹）。可用 `dir` 确认。

---

## 3. 创建虚拟环境并安装依赖（推荐，避免污染全局）

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -e .
```

> - 这里**故意不用 `activate`**，而是直接用 `.venv\Scripts\python.exe` 调用——这样在 AI 每次新开的终端里都稳定可用，不受「激活状态」「PowerShell 执行策略」影响。
> - 下文凡是 `python`，若你用了虚拟环境，请都替换成 `.venv\Scripts\python.exe`。
> - 安装较慢或超时，可加国内镜像：在 `pip install` 后追加 `-i https://pypi.tuna.tsinghua.edu.cn/simple`

**不想用虚拟环境**也行（直接装到全局）：
```powershell
python -m pip install -e .
```

### 兜底方案（万一 `pip install -e .` 失败）

`pip install -e .` 需要联网拉构建工具（setuptools/wheel）。若你处在**离线/内网/构建报错**（如 `invalid command 'bdist_wheel'`、`metadata-generation-failed`）的环境，**不必安装成包**，改用「装依赖 + 设置 PYTHONPATH」即可运行：

```powershell
.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:PYTHONPATH = "src"      # PowerShell；CMD 用：set PYTHONPATH=src
```
之后第 4、5 节的命令照常用（PYTHONPATH 已让 Python 找到 `src\coupon_engine`）。
注意：`$env:PYTHONPATH` 只在**当前终端窗口**有效，新开窗口要重设。


---

## 4. 生成示例数据（可选，但建议先做一次）

```powershell
.venv\Scripts\python.exe scripts\gen_sample_data.py 2000
```
成功后 `data\sample\` 下会出现 6 个 CSV，其中网站上传用的 3 张是
`customers.csv`、`products.csv`、`behavior.csv`。

---

## 5. 运行 —— 三种方式，任选

> **懒人一键（仅限有图形界面的人工操作）**：完成第 2 节拿到代码后，直接**双击 `start_windows.bat`**，它会自动建虚拟环境、装依赖并启动网站（等于把第 3、5① 步打包好了）。AI 自动化执行请仍按下面命令逐步来。

### 方式 ①：对客网站（最直观，推荐）⭐
```powershell
.venv\Scripts\python.exe -m uvicorn coupon_engine.api.main:app --port 8000
```
看到 `Uvicorn running on http://127.0.0.1:8000` 后，浏览器打开 **http://localhost:8000**。
- 直接点页面上的「**用示例数据体验**」即可立刻看到结果；
- 或上传第 4 节生成的 `customers.csv` / `products.csv` / `behavior.csv` 三个文件，再下载推荐结果（CSV/Excel）。
- 停止服务：在终端按 `Ctrl + C`。

> 如果你是 AI、无法开浏览器，可另开一个终端用命令验证（服务需保持运行）：
> ```powershell
> curl.exe "http://localhost:8000/api/demo?n_users=300"
> ```
> 返回一段含 `"summary"`、`"n_rows"` 的 JSON 即为成功。

### 方式 ②：命令行批量跑（离线出周报）
```powershell
.venv\Scripts\python.exe scripts\run_pipeline.py
```
终端会打印一份发券周报，并生成 `model.joblib`。

### 方式 ③：跑测试（确认环境健康）
```powershell
.venv\Scripts\python.exe -m pytest -q
```
预期结果：**20 passed**。若全部通过，说明你的环境完全 OK。

---

## 6. 常见问题速查（先查这里再记 bug）

| 现象 | 原因 | 解决 |
|------|------|------|
| `'python' 不是内部或外部命令` | 没装或没加 PATH | 重装并勾选 Add to PATH；或改用 `py` |
| 打开的是「应用商店」 | Win 自带的 python 别名 | 设置→应用→应用执行别名，关掉 python 的别名；或装官方版 |
| `pip install` 超时/SSL 报错 | 网络问题 | 命令加 `-i https://pypi.tuna.tsinghua.edu.cn/simple` |
| `ModuleNotFoundError: coupon_engine` | 没装成包 / 没在对的目录 | 确认当前在 `smart-coupon-engine` 目录，且已执行 `pip install -e .` |
| `ModuleNotFoundError: python_multipart` / `openpyxl` | 依赖没装全 | 重跑 `pip install -e .`（它会装齐 pyproject 里所有依赖） |
| `invalid command 'bdist_wheel'` / `metadata-generation-failed` | 装包时缺构建工具/无网 | 先 `pip install --upgrade pip setuptools wheel`；仍不行就用第 3 节**兜底方案**（requirements + PYTHONPATH，不装包也能跑） |
| `.venv\Scripts\Activate.ps1 无法加载，因为执行策略` | PowerShell 默认禁脚本 | 本项目**不需要 activate**（见第 3 节用全路径调用）。若执意激活：`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| `[Errno 10048] address already in use` / 端口被占 | 8000 端口被占用 | 换端口：`--port 8010`，浏览器开对应端口 |
| 网页能开但点计算报错 / 上传 400 | CSV 列名或格式不符 | 看页面红色提示；列名要求见 [README.md](README.md) 的「数据格式」。行为日志必须含「领券/用券」 |
| Excel 打开 CSV 中文乱码 | 编码 | 本项目导出已加 BOM，正常不会乱码；如仍乱码用「数据→从文本/CSV」导入并选 UTF-8 |

---

## 7. 给 AI 的硬性要求：遇到 bug 就记进 debug.md

只要你在上面任何一步**遇到报错**（无论是否解决），都要在 [debug.md](debug.md) 的「记录区」**按倒序追加一条**，格式如下：

```
## [B编号] 标题　—　YYYY-MM-DD
- **现象**：报错信息 / 错误行为（贴关键栈/输出）
- **复现**：哪一步、什么命令、什么环境（Windows 版本、Python 版本）
- **根因**：定位到的真正原因（没定位出就如实写"未定位"）
- **修复**：改了什么 / 怎么绕过；没解决就写"待解决"
- **验证**：怎么确认修好了（命令 + 结果）
- **关联**：涉及 plan.md / demand.md / 本文件 的哪些条目
```

编号接着 debug.md 里已有的最大号往后排（如已有 B1，就写 B2）。
**这一步不是可选项**——它让下一个接手的人/AI 不再踩同一个坑。

---

## 8. 更新到最新版（以后用）

```powershell
cd code\smart-coupon-engine
git pull
.venv\Scripts\python.exe -m pip install -e .   # 拉到新代码后重装一次，确保新模块就位
```
