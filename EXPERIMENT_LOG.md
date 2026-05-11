# AI 小说生成系统 — 实验日志

> 作者：张业成（清华大学）
> 项目路径：`D:/pythonPycharms/工具开发/063网络小说爬取`
> 最后更新：2026-05-09

## 1. 项目概述

### 1.1 研究目标

基于 1675 本网络小说语料（29.5 亿汉字），构建 AI 小说生成系统，目标是生成可在番茄小说/起点等平台发布并获取收益的长篇网络小说。

### 1.2 核心问题

1. **数据工程**：如何从原始爬取数据中提取高质量训练语料？
2. **训练策略**：RAG vs 微调 vs 继续预训练，哪种路线在现有算力下最优？
3. **生成质量**：如何控制长篇连贯性、爽点节奏、角色一致性？
4. **商业验证**：生成内容能否通过平台审核并获取有效阅读量？

### 1.3 算力资源

- **工作站 (workstation)**：4 × RTX 4090 (24GB each, 96GB total VRAM), Xeon 8352V 36C/72T, 256GB RAM, CUDA 13.1
- **本机 (wolf)**：RTX 3070 (8GB), 日常开发用
- GPU 2+3 完全空闲（~48GB VRAM），可独立使用不影响 GPU 0+1 上的 building_defect 任务

---

## 2. 数据采集

### EXP-2.0: 多源多平台网络小说语料采集

**Date**: 2026-04-28 ~ 2026-05-08
**Git**: `71a31e8`
**Status**: complete

#### Motivation

构建 AI 写小说系统的第一步是获取大规模、高质量、结构化的中文网络小说语料。需要覆盖主流分类（玄幻/都市/仙侠/言情等），同时采集多平台权重数据（收藏/月票/推荐/评分），用于后续训练数据的质量分级。

#### Method

**爬取架构**：分为三层——书单构建 → 匹配下载 → 统计补充。

```
书单构建层:
  qidian_booklist.py     起点移动端 SSR 数据 → 各分类×各榜单书目
  supplement_booklist.py  qbxsw.com 分类页/排行榜补充书目
      ↓ 合并去重
  booklist.json (1959 本)

匹配下载层:
  match_and_download.py   书单匹配 qbxsw book_id
  novel_scraper.py        核心爬虫（章节分页处理、断点续传）
  parallel_download.py    多 worker 并行调度
  auto_run.py             限流自动冷却+恢复
  proxy_pool.py           NekoBox sing-box 代理池（备用）

统计补充层:
  fetch_stats.py          起点收藏/月票/推荐
  fix_metadata.py         补生成缺失 metadata
  multi_platform_stats.py 起点/晋江/纵横/豆瓣 四平台采集
  jjwxc_stats.py          晋江排行榜书目+积分/收藏
  jjwxc_scraper.py        晋江盗版站正文爬取
```

**正文数据源**：

| 数据源 | URL | 类型 | 反爬 | 书籍数 |
|--------|-----|------|------|--------|
| 全本小说网 | qbxsw.com | 静态 HTML | 无（限流） | 1,669 |
| 镇魂小说 | zhenhunxiaoshuo.com | 静态 HTML | 无 | 6 |

**统计数据源**：

| 平台 | 采集方式 | 采集字段 | 覆盖率 |
|------|---------|---------|--------|
| 起点中文网 | 移动端 SSR (m.qidian.com) | 收藏/月票/推荐/字数/分类/标签/签约 | **92%** (1,543本) |
| 晋江文学城 | 搜索+详情页 (jjwxc.net, GBK) | 积分/收藏/书评 | 4% (67本) |
| 豆瓣读书 | suggest API + 详情页 | 评分/评价人数 | 1% (24本) |

**爬虫技术要点**：
- HTTP 请求：`urllib.request` 直连（绕过系统代理），带 `ProxyHandler({})` 强制直连
- 并发控制：`ThreadPoolExecutor`，短书 4 线程 / 长书(≥800章) 3 线程
- 容错：3 次重试 + 指数退避 + 连续 5 次失败触发冷却（2^n 秒，上限 120s）
- 断点续传：已下载章节记录在 `chapters.jsonl`，增量追加
- 章节分页：处理 `class="next"` 分页链接，最多 20 页合并
- 文本清洗（爬取时）：去 script/style 标签，去 `<br>/<p>` 转换行，去 8 条广告正则

**输出格式**（每本书一个目录）：
```
data/书名_作者/
  metadata.json        元信息 + 多平台统计
  chapters.jsonl       每行一个 JSON: {index, title, word_count, content}
  full_text.txt        纯文本合并版
  chapters/            逐章 txt 文件
```

#### Results

**总体规模**：

| 指标 | 数值 |
|------|------|
| 书单总量 | 1,959 本 |
| 实际下载 | **1,675** 本（有 chapters.jsonl） |
| 总章节 | **1,451,957** 章 |
| word_count 总计 | 35.2 亿字符 |
| 纯汉字总计 | **29.54 亿**字 |
| 磁盘占用 | 33 GB |
| 采集周期 | ~10 天 |

**平台统计覆盖**：

| 平台 | 覆盖书数 | 覆盖率 |
|------|---------|--------|
| 起点(收藏/月票/推荐) | 1,543 | **92%** |
| 晋江(积分/收藏) | 67 | 4% |
| 豆瓣(评分) | 24 | 1% |

**起点收藏数分布**（1,543 本有数据）：

| 区间 | 书数 | 说明 |
|------|------|------|
| ≥ 100 万 | 106 | 头部爆款 |
| 10 万 ~ 100 万 | 390 | 热门精品 |
| 1 万 ~ 10 万 | 535 | 优质作品 |
| 1 千 ~ 1 万 | 183 | 普通作品 |
| < 1 千 | 329 | 长尾/新书 |

- 最高收藏：18,858,848（TOP3 均在 1880 万级别）
- 中位数收藏：38,775
- 均值收藏：318,932

**起点月票**：1,205 本有月票数据，最高 121,700，中位数 178

**起点推荐票**：1,509 本有推荐数据，最高 97,491,698，中位数 29,025

**起点分类分布**（qidian_category）：

| 分类 | 书数 | | 分类 | 书数 |
|------|------|-|------|------|
| 玄幻 | 235 | | 古代言情 | 84 |
| 都市 | 188 | | 现代言情 | 75 |
| 轻小说 | 156 | | 奇幻 | 55 |
| 仙侠 | 153 | | 诸天无限 | 54 |
| 玄幻言情 | 104 | | 科幻 | 51 |
| 历史 | 101 | | 游戏 | 51 |

**qbxsw 分类分布** TOP 5：玄幻 177 / 仙侠 151 / 言情 150 / 都市 143 / 悬疑 140

**高频标签** TOP 10：升级(327) / 穿越(274) / 系统流(170) / 热血(161) / 轻松(133) / 爽文(76) / 无敌(60) / 种田文(54) / 女强(43) / 赚钱(39)

**连载状态**：连载中 1,036 / 已完本 501 / 出版精品 9

**签约状态**：签约作品 115 / 独家作品 6（仅 121 本有签约信息）

**章节数分布**：

| 区间 | 书数 | 占比 |
|------|------|------|
| < 100 章 | 8 | 0.5% |
| 100 ~ 500 章 | 655 | 39.1% |
| 500 ~ 1000 章 | 548 | 32.7% |
| 1000 ~ 2000 章 | 338 | 20.2% |
| > 2000 章 | 126 | 7.5% |

- 最少 3 章，最多 11,713 章，中位数 628 章，均值 867 章

**豆瓣评分**（24 本有数据）：均值 7.4，范围 5.3 ~ 9.0

**晋江积分**（67 本有数据）：最高 21,866,962,944，中位数 111,113

#### Analysis

- **Established**: qbxsw.com 作为正文源效率极高（纯静态 HTML、无 JS 反爬），10 天完成 1,675 本下载
- **Established**: 起点移动端 SSR 数据可高效获取收藏/月票/推荐等权重数据，92% 覆盖率足以支撑质量分级
- **Supported**: 晋江/豆瓣覆盖率低（4%/1%），主因是站点反爬机制更严格（晋江 GBK 编码 + 搜索限流，豆瓣 API 限制）
- **Preliminary**: 未完成的数据源包括：晋江正文（ixdzs8 需 Playwright 应对 JS 反爬）、番茄小说（字体加密待破解）、纵横中文网（需 JS 渲染）
- **Constraint**: 约 300 本有 chapters.jsonl 但缺失 metadata（已由 fix_metadata.py 补生成）
- 标签分布显示语料以"升级流"(327)、"穿越"(274)、"系统流"(170) 为主，符合网文主流类型
- → 下一步：EXP-3.1 精确统计纯汉字数，评估 word_count 字段的偏差

#### Artifacts

- 爬虫代码：`scraper/`（12 个 .py 模块）
- 原始数据：`data/`（33GB，1,675 个子目录）
- 书单：`booklist.json`（1,959 本）
- 晋江书目：`jjwxc_books.json`（独立的晋江统计数据）
- 下载日志：`data/download_log.json`
- Worker 日志：`logs/worker_*.log`

---

## 3. 数据工程

### EXP-3.1: 原始语料统计与质量审计

**Date**: 2026-05-08
**Git**: `71a31e8`
**Status**: complete

#### Motivation

爬虫项目已完成 1959 本小说的下载（qbxsw.com 源），但 `chapters.jsonl` 中的 `word_count` 字段使用 `len(content)` 计算，包含标点、空格、换行符和网站水印文本，不代表真实汉字数量。需要精确统计纯汉字数，评估真实语料规模。

#### Method

- 遍历所有 `data/*/chapters.jsonl`，逐行解析
- 使用 `re.findall(r'[\u4e00-\u9fff]', content)` 统计 CJK 统一表意文字
- 对比 `word_count`（`len(content)`）与纯汉字数的差异

#### Results

| 指标 | 数值 |
|------|------|
| 有 chapters.jsonl 的书 | 1,675 本 |
| 缺失 chapters.jsonl | 1 本 |
| `word_count` 字段总计 | **35.22 亿**字符 |
| 纯汉字数 | **29.54 亿**字 |
| 汉字占比 | 83.9% |
| data/ 目录大小 | 33 GB |

10 本采样书的汉字占比范围：70.4% ~ 87.5%，差异来自不同书的水印密度和标点风格。

#### Analysis

- **Established**: `word_count` 字段高估真实汉字量约 19%，后续所有统计和训练数据量估算应使用纯汉字数
- 29.54 亿汉字 ≈ 40-50 亿 tokens（中文分词后），这个量级足够支撑 LoRA 微调甚至领域继续预训练
- 非汉字部分包括：正常标点（~10%）、网站水印文本、空白符、偶发乱码

#### Artifacts

- 数据目录：`data/`（33GB，1675 本书）
- 元数据：`data/*/metadata.json`（含起点收藏/月票/推荐等统计）

---

### EXP-3.2: 语料清洗管线

**Date**: 2026-05-09
**Git**: `b2dc48c`
**Status**: complete

#### Motivation

EXP-3.1 发现原始数据中约 16% 为非汉字内容，其中包含大量网站插入的水印文本（如"小主，这个章节后面还有哦，请点击下一页继续阅读"）。这些噪声会污染训练数据，需要在训练前系统清洗。同时需要基于起点收藏数对语料做质量分级，为后续分层训练做准备。

#### Method

清洗管线 `cleaning/clean_corpus.py`，5 步处理：

1. **水印/广告去除**：精确匹配 2 条高频水印 + 正则匹配 19 条广告模式，逐行过滤
2. **控制字符清理**：删除 `\x00-\x1f`、零宽字符（`\u200b-\u200f`, `\ufeff` 等）
3. **标点归一化**：半角引号→中文引号，连续省略号归一化为 `……`
4. **空白归一化**：多余空格压缩，多空行压缩为单空行
5. **短章过滤**：纯汉字 < 100 字的章节丢弃

质量分级基于起点收藏数：

$$\text{Quality Tier} = \begin{cases} S & \text{collect} \geq 100{,}000 \\ A & 10{,}000 \leq \text{collect} < 100{,}000 \\ B & 1{,}000 \leq \text{collect} < 10{,}000 \\ C & \text{collect} < 1{,}000 \text{ 或无数据} \end{cases}$$

| 参数 | 值 |
|------|-----|
| 并行进程数 | 8 (ProcessPoolExecutor) |
| 水印精确匹配 | 2 条 |
| 广告正则模式 | 19 条 |
| 短章阈值 | 100 汉字 |

#### Results

| 指标 | 清洗前 | 清洗后 | 变化 |
|------|--------|--------|------|
| 有效书籍 | 1,675 | 1,675 | — |
| 章节数 | 1,443,664 | **1,441,955** | -1,709 (0.12%) |
| 纯汉字 | 29.54 亿 | **29.42 亿** | -1,194 万 (0.40%) |
| 水印行删除 | — | — | **566,592 行** |

质量分级分布：

| 等级 | 书籍数 | 汉字量 | 占比 |
|------|--------|--------|------|
| **S** (收藏≥10万) | 496 | **10.93 亿** | 37.2% |
| **A** (1万-10万) | 535 | **10.23 亿** | 34.8% |
| B (1千-1万) | 183 | 2.75 亿 | 9.4% |
| C (<1千/无数据) | 461 | 5.50 亿 | 18.7% |

分类分布 TOP 5：

| 分类 | 书数 | 汉字量 |
|------|------|--------|
| 玄幻 | 194 | 5.20 亿 |
| 都市 | 252 | 5.16 亿 |
| 仙侠 | 154 | 3.54 亿 |
| 轻小说 | 156 | 2.82 亿 |
| 历史 | 110 | 2.05 亿 |

清洗耗时：**174.2 秒**（8 进程并行，本机执行）

#### Analysis

- **Established**: 清洗损耗极低（0.40%），水印去除有效（56.6 万行），说明原爬虫 `clean_text()` 已做了基础清洗，本次管线主要补充了站点插入的分页提示文本
- **Established**: S+A 两档合计 1,031 本、21.16 亿字，占总量 72%，这是高质量训练核心池
- **Supported**: 短章丢弃 1,709 章，影响极小（0.12%），阈值 100 汉字合理
- **Preliminary**: 质量分级仅基于起点收藏数单一维度，C 级中可能存在高质量但非起点平台的书（如晋江系），后续可结合 jjwxc_score 做多维评级
- → 下一步：EXP-4.1 训练数据构造（从清洗后语料构建 instruction-response 格式）

#### Artifacts

- 清洗代码：`cleaning/clean_corpus.py`
- 清洗后数据：`data_cleaned/`（1675 个子目录）
- 清洗后章节：`data_cleaned/*/chapters_cleaned.jsonl`（字段：index, title, hanzi_count, content）
- 清洗后元数据：`data_cleaned/*/metadata.json`（含 cleaning 字段）
- 汇总报告：`data_cleaned/cleaning_report.json`
- 逐本详情：`data_cleaned/cleaning_detail.jsonl`

---

## 4. 训练策略（待开展）

### EXP-4.1: 训练数据构造

**Date**: 2026-05-09
**Git**: `b2dc48c`
**Status**: ready（代码已完成并调试通过，待工作站全量运行）

#### Motivation

EXP-3.2 产出了 29.42 亿字清洗语料（S+A 级 21.16 亿字），但原始章节文本不能直接用于指令微调。需要构造 Alpaca 格式的 instruction-response 训练对，让模型学会"续写"、"从大纲展开"、"风格控制"三种核心能力。

#### Method

构造脚本 `cleaning/build_train_data.py`，三类任务：

**A. 续写任务（主力，预估 ~50-60%）**
- 将相邻章节拼接为连续文本
- 滑动窗口切片：context 800-2000 字 → target 400-1200 字，步长 1500 字
- 截断点对齐到句末标点（`。！？…」』】`）
- 过滤：context/target 汉字数不足阈值的丢弃

**B. 大纲展开（~25-30%）**
- 用章节标题 + 首段（前 200 字截到句号）作为"伪大纲"
- 整个章节作为 output（自监督，不依赖外部 LLM API）
- 只对 ≥1500 汉字的章节生成（短章不适合做大纲任务）
- input 包含：类型、作品名、章节标题、章节概要

**C. 风格控制（~15-20%）**
- 每章随机抽取 1 个 300-800 字片段
- 自动检测场景关键词（战斗/修炼/感情/日常/商战）
- 随机搭配风格词（热血激昂/轻松幽默/紧张悬疑等）
- 3 种 prompt 模板随机选取

| 参数 | 值 |
|------|-----|
| context 长度 | 800-2000 字 |
| target 长度 | 400-1200 字 |
| 滑动步长 | 1500 字 |
| 大纲最短章节 | 1500 汉字 |
| 风格片段长度 | 300-800 字 |
| train/val 切分 | 95%/5% |
| 输出格式 | Alpaca JSON（LLaMA-Factory 兼容） |
| 随机种子 | 42 |

#### Results（3 本书调试）

| 指标 | 值 |
|------|-----|
| 处理书籍 | 3 本 |
| 总样本数 | 4,157 条 |
| 续写 | 1,852 (44%) |
| 大纲展开 | 1,157 (27%) |
| 风格控制 | 1,148 (27%) |
| 耗时 | 1.1s |

样本质量验证：
- 续写：input 1014 汉字 → output 648 汉字（长度合理，截断在句号处）
- 大纲展开：含类型+书名+标题+概要 → 1844 汉字完整章节
- 风格控制：指令含分类+场景+风格+字数 → 427 汉字片段

外推估算：S+A 级 1,031 本 × ~1,400 条/本 ≈ **140-150 万条训练样本**

#### Analysis

- **Established**: 三类样本构造逻辑正确，样本质量通过人工抽检
- **Supported**: 续写任务的滑动窗口方式高效，每本长篇小说可产出上千条续写对
- **Preliminary**: 大纲展开使用"伪大纲"（首段截取），质量不如真实大纲→正文对。后续可用 LLM API 批量生成章节大纲作为增强（Phase 2）
- 比例调参空间：如果续写效果已经很好，可以减少续写比例，增加大纲展开的权重

**全量运行计划**：
```bash
# 在工作站执行（拉取代码后）
python -m cleaning.build_train_data --tier S,A --workers 16
```

#### Artifacts

- 构造代码：`cleaning/build_train_data.py`
- 输出目录：`data_train/`（全量运行后生成）
- 输出格式：`train_S+A.json` / `val_S+A.json` / `dataset_info_S+A.json`

---

### EXP-4.2: Qwen2.5-14B LoRA 微调

**Status**: planned

#### Method（方案）

在工作站 GPU 2+3（48GB VRAM）上执行，不影响 GPU 0+1 上的 building_defect 任务。

| 项目 | 选择 | 理由 |
|------|------|------|
| 基座模型 | Qwen2.5-14B-Instruct | 中文最强开源指令模型，工作站已有 qwen 环境 |
| 微调方法 | LoRA (rank=64, alpha=128) | 2×4090 够用，训练速度快 |
| 训练框架 | LLaMA-Factory | 一站式，原生支持 Qwen + LoRA + DeepSpeed |
| 精度 | bf16 + gradient checkpointing | 节省显存 |
| 数据格式 | Alpaca JSON | EXP-4.1 直接输出 |

**训练计划（两阶段）**：
1. **快速验证**：取 10 万条样本，1 epoch，预计 2-4 小时。目标：确认 loss 下降、生成文本通顺
2. **全量训练**：S+A 级全部样本（~150 万条），2-3 epochs，预计 3-5 天

**工作流**：
```
本机写代码 → git push → 工作站 git pull → 工作站运行训练
→ 本机 ssh 查看 loss 曲线 → 调参 → 再 push
```

**关键超参（初始值，待调）**：
- learning_rate: 2e-4
- batch_size: 4 (per device)
- gradient_accumulation_steps: 8
- warmup_ratio: 0.05
- max_length: 4096 tokens
- lora_rank: 64
- lora_alpha: 128
- lora_target: all linear layers

---

### EXP-4.3: 生成系统搭建

**Status**: planned

微调模型 + RAG 检索（向量库检索相似桥段）+ 长篇管理（角色卡、世界观、章节大纲）→ 逐章生成管线。

核心架构：
```
用户输入：类型 + 主角设定 + 世界观 + 总大纲
    ↓
章节级大纲规划（50-100 章节结构）
    ↓
逐章生成循环：
  前文摘要 + 本章大纲 + RAG 检索相似桥段 → 微调模型生成
  → 连贯性检查 → 角色一致性检查 → 输出
```

---

## 5. 工程 & Bug 修复

### ENG-1: 项目目录重组

**Date**: 2026-05-09

将扁平的项目结构重组为模块化结构：
- `scraper/`：爬虫模块（12 个 .py 文件）
- `cleaning/`：数据清洗模块
- `tests/`：测试脚本
- 修复所有 `BASE_DIR` / `OUTPUT_DIR` 路径引用（指向项目根而非 scraper/ 子目录）
- 修复跨模块导入（`parallel_download.py` → `scraper/novel_scraper.py`，`match_and_download.py` → `from scraper import novel_scraper`）

### ENG-2: GitHub 仓库 + 工作站代码同步

**Date**: 2026-05-09
**Git**: `b2dc48c`

项目推送到 GitHub：`https://github.com/24kchengYe/web-novel-crawler`

**工作站同步**：
- 路径：`D:\projects\web-novel-crawler`（workstation, SSH alias `workstation`）
- 工作站 git 有全局代理 `socks5://127.0.0.1:1080`，clone/pull 需要覆盖：
  ```
  git -c http.proxy= -c https.proxy= clone/pull
  ```
- Python 导入验证通过：`import cleaning.clean_corpus` OK

**开发工作流**：
```
本机(wolf) 写代码 → git push origin master
    ↓
工作站(workstation) git pull → 运行清洗/训练/推理
    ↓
本机 ssh 查看结果 → 调参 → 再 push
```

**待办**：工作站需要拷贝 `data/`（33GB）到 `D:\projects\web-novel-crawler\data\`，git 不跟踪数据目录。

---

### EXP-2.1: 多渠道语料扩充

**Date**: 2026-05-09
**Git**: 待提交
**Status**: in_progress

#### Motivation

EXP-2.0 采集了 1,675 本小说（29.54 亿汉字），但存在分类短板：悬疑仅 55 本、科幻 98 本、短篇几乎为零。同时仅依赖单一数据源（qbxsw.com），语料多样性不足。需要从多个渠道扩充：开源数据集（零成本）+ 新站点爬取（增量）。

#### Method

**A. 开源数据集下载**（`scraper/download_datasets.py`）

| 数据集 | 来源 | 规模 | 格式 | 分类 |
|--------|------|------|------|------|
| webnovel_cn | HuggingFace (zxbsmk) | 50K 条 (子集) / 完整版 2170 万条 | Alpaca instruction | 混合（12,560 本网文） |
| chinese-novel-dataset | HuggingFace (kkcmbx) | 3,862 条 | Alpaca instruction | 混合 |
| Chinese-Pixiv-Novel | HuggingFace (wuliangfo) | 145,163 本, 12.9GB | text + meta | 同人/二次创作 |
| LongData-Corpus 小说 | 清华云盘 | 长文本(>16K字) | JSON | 长篇小说 |
| GuoFeng-Webnovel | GitHub | 多语言网文 | mixed | 中英对照 |

**B. 多站点爬虫框架**（`scraper/sites/`）

统一基类 `NovelSiteBase`，每个站点独立模块，标准接口：
- `get_book_list(category)` → 书籍列表
- `get_chapters(book_id)` → 章节列表
- `get_chapter_content(url)` → 正文
- `get_ad_patterns()` → 站点特有广告

| 站点模块 | 域名 | 预估增量 | 反爬难度 | 输出目录 |
|---------|------|---------|---------|---------|
| quanben.py | quanben-xiaoshuo.com / quanben.io / quanben.net | ~500-1000 本 | 低 | data_quanben/ |
| biquge.py | xbiquge.com.cn | 数千本 | 中(Cloudflare) | data_biquge/ |
| shu69.py | 69shuba.com (域名常变) | 数千本 | 低-中 | data_69shu/ |
| dingdian.py | dingdiann.com (域名常变) | 数千本 | 中 | data_dingdian/ |

所有站点输出格式统一：`data_{site}/书名_作者/metadata.json + chapters.jsonl`

**C. 分类补充重点**

针对现有短板优先爬取：
- 悬疑推理：各站点的悬疑/灵异分类
- 科幻：各站点的科幻分类
- 女频言情：笔趣阁和 quanben 的言情分区
- 短篇集：如果有短篇小说专区也收录

#### Analysis

- webnovel_cn 完整版 2170 万条如能获取，直接就是海量训练数据（但需百度网盘下载）
- Pixiv 小说数据集 12.9GB 含大量 R-18 内容，需要在训练时做内容过滤
- 盗版站域名不稳定（尤其 69shu、顶点），代码中保留多域名切换能力
- 各站点的书目有大量重叠（同一本书在多个站都有），后续需要跨站去重

#### Results

**Phase 1: 自研爬虫探测（2026-05-09 ~ 05-10）**

自研 Playwright + HTTP 爬虫的站点探测结果：

| 站点 | 可达性 | 书单 | 章节 | 正文 | 结论 |
|------|--------|------|------|------|------|
| quanben-xiaoshuo.com | OK | OK (200本/页) | FAIL (JS) | — | 放弃 |
| xbiquge.com.cn | OK (慢) | OK | OK | OK (Playwright) | 可行但极慢 |
| 69shuba.com | FAIL (Cloudflare) | — | — | — | 放弃 |
| dingdiann.com | FAIL | — | — | — | 放弃 |

关键发现：2026 年盗版站普遍使用 JS 加密正文（Base64 + `document.writeln`），不是简单的 JS 延迟加载。Playwright 效率极低（~6s/章），biquge 跑了数小时仅完成 4 本。

**Phase 2: so-novel 工具发现（2026-05-11）**

发现开源工具 [so-novel](https://github.com/freeok/so-novel)（6.7K Star，Java），它通过**内嵌 JS 解密引擎 + CSS 选择器**在服务端直接解密正文，速度 ~70 章/秒（比 Playwright 快 450 倍）。

so-novel 核心技术：
- OkHttp3 请求 + Jsoup CSS 选择器解析（非正则）
- GraalJS 引擎执行 rules 中的 `@js:` Base64 解密脚本
- Java Virtual Threads 50 并发
- 25 个站点的手工适配规则（`rules/*.json`）

测试验证：斗破苍穹 1179 章，**16 秒**下载完成（73.7 章/秒）。

**Phase 3: 全量书目发现（2026-05-11）**

编写 `discover_books.py`，扫描 5 个可直接解析分类页的站点：

| 站点 | 书目数 | 分类数 | 扫描方式 |
|------|--------|--------|---------|
| 笔趣阁22 (22biqu.com) | 16,039 | 8 | HTTP + 智能过滤 |
| 笔趣阁365 (biquge365.net) | 4,678 | 7 | HTTP + CSS 选择器 |
| 顶点小说 (wxsy.net) | 3,907 | 9 | HTTP + 智能过滤 |
| 书林文学 (shu009.com) | 1,772 | 8 | HTTP + CSS 选择器 |
| 燃文小说网 (ranwen8.cc) | 1,551 | 9 | HTTP + CSS 选择器 |

汇总结果：

| 指标 | 数值 |
|------|------|
| 总书目 (按 URL) | **32,542** |
| 总书目 (按书名去重) | **27,947** |
| 可新增 (不在 data/) | **27,545** |
| 已有 (data/) | 1,677 |

分类分布：科幻 3,930 / 都市 3,927 / 玄幻 3,678 / 网游 3,300 / 言情 3,098 / 历史 2,517 / 武侠 2,292 / 灵异 1,652 / 仙侠 1,006

**Phase 4: 开源数据集下载**

| 数据集 | 状态 | 规模 |
|--------|------|------|
| webnovel_cn | **done** | 50K 条, 2,642 万汉字 |
| chinese-novel-dataset | **done** | 3,862 条, 140 万汉字 |
| GuoFeng-Webnovel | **done** | GitHub 仓库 |
| **Chinese-Pixiv-Novel** | **done** | 13GB（single_turn 3.5GB + multi_turn 3.6GB + incremental 3.5GB，已是 Alpaca 训练格式） |
| LongData-Corpus | pending | 需手动从清华云盘下载 |

#### Analysis

- **Established**: so-novel 通过 JS 引擎服务端解密，比 Playwright 浏览器渲染快 450 倍，是 2026 年爬取 JS 加密小说站的正确方案
- **Established**: 5 个站分类页可静态解析书目，30 页/分类可发现 27,947 本不重复书目
- **Established**: Pixiv 数据集 13GB 已包含现成的 Alpaca 格式训练数据（single_turn + multi_turn），可直接合入训练
- **Constraint**: so-novel WebUI API 只有搜索接口（`/search/aggregated`），没有分类浏览接口，需自建 discover_books.py 补充
- **Constraint**: 全量下载 27,545 本 × ~20s/本 ≈ 6.4 天

→ 下一步：EXP-2.2 统一数据格式 + 全量下载

#### Artifacts

- 书目发现器：`scraper/discover_books.py`
- so-novel 批量下载器：`scraper/sonovel_batch.py`
- so-novel TXT 转换器：`scraper/convert_sonovel.py`
- 开源数据集下载器：`scraper/download_datasets.py`
- so-novel 工具：`tools/SoNovel/`（含 rules、config、JRE）
- 书目清单：`discovered_books.json`（27,947 本）
- 开源数据：`data_opensource/`（webnovel_cn + chinese-novel + GuoFeng）
- Pixiv 数据：`Chinese-Pixiv-Novel/`（13GB）

---

### EXP-2.2: 数据统一格式化 + 全量下载

**Date**: 2026-05-11
**Status**: in_progress

#### Motivation

当前数据分散在多个目录（data/、data_opensource/、Chinese-Pixiv-Novel/、tools/SoNovel/downloads/），格式不统一（qbxsw 的 metadata.json 字段 vs so-novel 的 TXT vs Pixiv 的 Alpaca JSON）。需要在全量下载前设计统一格式，确保所有数据源合并后结构一致，方便后续清洗、训练和搭建小说网站。

#### Method

**统一存储格式（两层架构）**：

第一层：`library_index.json` — 全局书目索引，一个文件概览全库

第二层：`books/分类/书名_作者/` — 按分类组织的书籍数据
```
books/
  科幻/
    斗破苍穹_天蚕土豆/
      book.json            # 完整元数据（结构化分组）
      chapters.jsonl       # 章节内容（每行一章）
  玄幻/
    ...
```

**book.json 统一字段**：
```json
{
  "book_id": "唯一标识",
  "title": "书名",
  "author": "作者",
  "description": "简介",
  "classification": {
    "category": "分类",
    "sub_category": "子分类",
    "tags": ["标签1", "标签2"],
    "gender": "male/female"
  },
  "stats": {
    "chapter_count": 0,
    "word_count": 0,
    "hanzi_count": 0,
    "status": "连载中/已完本"
  },
  "quality": {
    "tier": "S/A/B/C",
    "qidian_collect": null,
    "qidian_recom": null,
    "douban_rating": null,
    "jjwxc_score": null
  },
  "sources": [
    {"site": "来源站", "url": "URL", "scraped_at": "时间"}
  ]
}
```

**chapters.jsonl 统一行格式**：
```json
{"index": 1, "title": "章节名", "word_count": 0, "hanzi_count": 0, "content": "正文"}
```

**执行步骤**：
1. 写 `convert_to_unified.py`：将 data/、so-novel TXT、Pixiv JSON 统一转换
2. 启动 so-novel 全量下载（27,545 本，~6天）
3. 下载过程中持续转换新下载的 TXT
4. 全部完成后生成 library_index.json

**后续规划**（下载完成后）：
- 导入 PostgreSQL + pgvector 数据库
- 全文检索 + 向量检索（RAG）
- 小说网站/APP 后端接口

---

## 6. 下一步

1. **EXP-2.2 执行**：写统一格式转换脚本 + 启动 so-novel 全量下载
2. **全量清洗**：所有数据下载转换完后，统一运行 clean_corpus.py
3. **训练数据构造**：合并所有来源（qbxsw + so-novel + Pixiv + 开源），统一构造
4. **EXP-4.2**: Qwen2.5-14B LoRA 微调（工作站 GPU 2+3）
5. 数据库搭建：PostgreSQL + pgvector

---

## 7. 实验索引

| EXP-ID | 标题 | 日期 | 状态 | 关键结果 |
|--------|------|------|------|----------|
| EXP-2.0 | 多源多平台语料采集 | 2026-04-28 ~ 05-08 | complete | 1,675 本、29.54 亿汉字、起点覆盖 92% |
| EXP-2.1 | 多渠道语料扩充 | 2026-05-09 ~ 05-11 | complete | so-novel 发现（450x提速）、5站扫描 27,947 本书目、Pixiv 13GB |
| EXP-2.2 | 数据统一格式化 + 全量下载 | 2026-05-11 | in_progress | 统一 book.json + chapters.jsonl 格式，全量下载 27,545 本 |
| EXP-3.1 | 原始语料统计与质量审计 | 2026-05-08 | complete | 29.54 亿汉字，word_count 高估 19% |
| EXP-3.2 | 语料清洗管线 | 2026-05-09 | complete | 29.42 亿字，去除 56.6 万行水印，S+A 级 21.16 亿字 |
| EXP-4.1 | 训练数据构造 | 2026-05-09 | ready | 代码完成，待全量数据就绪后运行 |
| EXP-4.2 | Qwen2.5-14B LoRA 微调 | — | planned | — |
| EXP-4.3 | 生成系统搭建 | — | planned | — |

---

## 附录

### A. 数据资产清单

| 来源 | 路径 | 规模 | 格式 | 状态 |
|------|------|------|------|------|
| qbxsw 原始爬取 | `data/` | 1,675 本, 29.42 亿汉字, 33GB | metadata.json + chapters.jsonl | done |
| webnovel_cn | `data_opensource/webnovel_cn/` | 50K 条, 2,642 万汉字 | Alpaca JSONL | done |
| chinese-novel | `data_opensource/chinese-novel-dataset/` | 3,862 条, 140 万汉字 | Alpaca JSONL | done |
| GuoFeng-Webnovel | `data_opensource/GuoFeng-Webnovel/` | 多语言网文 | mixed | done |
| Pixiv 小说 | `Chinese-Pixiv-Novel/` | 13GB (single/multi/incremental) | Alpaca JSON | done |
| so-novel 下载 | `tools/SoNovel/downloads/` | 目标 27,545 本 | TXT | downloading |
| 书目清单 | `discovered_books.json` | 27,947 本不重复 | JSON | done |

### B. 代码索引

| 模块 | 文件 | 说明 |
|------|------|------|
| 爬虫 | `scraper/novel_scraper.py` | qbxsw 核心爬虫 |
| 爬虫 | `scraper/parallel_download.py` | 并行下载调度 |
| 爬虫 | `scraper/auto_run.py` | 限流自动恢复 |
| 书单 | `scraper/qidian_booklist.py` | 起点榜单采集 |
| 统计 | `scraper/multi_platform_stats.py` | 多平台统计采集 |
| 发现 | `scraper/discover_books.py` | 5站分类页书目发现器 |
| 下载 | `scraper/sonovel_batch.py` | so-novel WebUI API 批量下载 |
| 转换 | `scraper/convert_sonovel.py` | TXT → 标准格式转换 |
| 开源 | `scraper/download_datasets.py` | HuggingFace 数据集下载 |
| 清洗 | `cleaning/clean_corpus.py` | 语料清洗管线 |
| 训练 | `cleaning/build_train_data.py` | 训练数据构造（Alpaca 格式） |
| 工具 | `tools/SoNovel/` | so-novel Java 下载工具 |
