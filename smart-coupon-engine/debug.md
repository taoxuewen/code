# debug.md — Bug 记录

> 每次出现 bug、用户让我修复后，我把「现象 → 定位 → 修复 → 验证」整理记录在这里。
> 目的：让任何新接手的人/AI 知道**这个项目踩过哪些坑、为什么某段代码长这样**，避免重复犯错。
> 格式：按时间倒序，最新在最上面。
>
> 配套：`plan.md`（架构）、`demand.md`（需求）、`RUN_ON_WINDOWS.md`（Windows 运行手册）。
>
> **给在 Windows 上运行的 AI**：若你照 `RUN_ON_WINDOWS.md` 执行时报错，请按下方模板在「记录区」倒序追加一条（编号接最大号往后排）。这是硬性要求。

---

## Bug 模板（复制使用）

```
## [B编号] 标题　—　YYYY-MM-DD
- **现象**：报错信息 / 错误行为（贴关键栈/输出）
- **复现**：怎么触发的（命令 / 输入 / 环境）
- **根因**：定位到的真正原因
- **修复**：改了什么（文件 : 行 / 函数），为什么这样改
- **验证**：怎么确认修好了（命令 + 结果）
- **关联**：涉及 plan.md / demand.md 的哪些条目；是否引入新约束
```

---

## 记录区

## [B1] 源码包 `data/` 被根 .gitignore 误伤，从未推上 GitHub　—　2026-06-06
- **现象**：在 Windows / 任意机器上 `git clone` 后跑项目，会 `ModuleNotFoundError`——`src/coupon_engine/data/` 整个包（`loader.py` / `synth.py` / `__init__.py` 等）在远端缺失。本地能跑（文件在磁盘上），但克隆下来跑不起来。
- **复现**：`git ls-tree -r --name-only HEAD -- smart-coupon-engine/src/coupon_engine/data/` 返回空；`git check-ignore -v <该目录下文件>` 命中规则 `.gitignore:60:data/`。
- **根因**：仓库**根目录** `.gitignore` 有一条 `data/`（本意忽略数据集），但 gitignore 的目录模式会匹配**任意层级**的同名目录，于是把源码包 `src/coupon_engine/data/` 也忽略了。该包从 D1 起就从未进入版本库（新文件被静默忽略，`git add` 不报错也不添加）。
- **修复**：在根 `.gitignore` 的 `data/` 之后加白名单例外，且只放行 `.py`（避免把 `__pycache__` 重新纳入）：
  ```
  !smart-coupon-engine/src/coupon_engine/data/
  !smart-coupon-engine/src/coupon_engine/data/*.py
  ```
  然后 `git add` 整个 data 包并提交推送（commit 27540cc）。
- **验证**：`git ls-tree -r --name-only HEAD -- .../data/` 列出全部 5 个 .py；`git check-ignore .../__pycache__/*.pyc` 仍命中（缓存依旧被忽略）；全量排查 `smart-coupon-engine` 下所有 .py 均已跟踪。
- **关联**：教训——**广义忽略名（data/、tmp/、build/…）可能误伤同名源码目录**；提交后应抽查 `git ls-tree HEAD` 确认关键源码确实入库。涉及 plan.md 目录结构第 3 节。
