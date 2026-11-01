# arXiv Daily Paper Bot

每天抓取 arXiv cs.IR / cs.CL / cs.CV 的新论文，用 DeepSeek 做粗排、精排和中文翻译，
推送到飞书群，并生成静态 HTML 部署到 GitHub Pages。

本仓库基于 Doragd/Algorithm-Practice-in-Industry 的 paperBotV2/arxiv_daily 整理。
原版硬编码了作者私有的飞书卡片模板，fork 后无法直接推送；本版改成通用卡片，
并修复了工作流里的失败退出码问题。

## 1. 架构

    GitHub Actions (03:23 UTC / 手动)
      -> arXiv API 抓取最近 36h 论文
      -> 去重（前一天 ID + 当天缓存）
      -> DeepSeek 粗排，过滤低分
      -> DeepSeek 精排 + 翻译 Top-N
      -> 保存 data/YYYYMMDD.json 和 status/
      -> 生成 output/arxiv_YYYYMMDD.html
      -> 飞书自定义机器人：通用 interactive 卡片，分片发送
      -> commit 到 main + 部署 gh-pages

## 2. 目录

    .github/workflows/arxiv_daily_full.yml
    paperBotV2/arxiv_daily/
      arxiv.py                 抓取 + 粗排 + 精排 + 翻译
      prompts.py               LLM prompts
      feishu_sender.py         通用飞书卡片发送器（本版新增）
      generate_arxiv_html.py   HTML 生成
      status.py                运行状态 / CSV
      data/                    每天 JSON + 发送标记
      status/                  运行状态 JSON/CSV
      output/                  HTML + static 模板
    examples/sample_papers.json
    requirements.txt
    README.md

## 3. 本地验证（默认只预览，不发送）

    cd 项目根目录
    python -m venv .venv
    .venv\Scripts\activate
    pip install -r requirements.txt

    Copy-Item .env.example .env
    # 编辑 .env：填 FEISHU_URL、DEEPSEEK_API_KEY
    # 本地默认 FEISHU_DRY_RUN=1，不会真的发飞书

    $env:FEISHU_DRY_RUN="1"
    $env:RETURN_PAPERS="3"
    python -m paperBotV2.arxiv_daily.feishu_sender --data examples\sample_papers.json

预览会写到 paperBotV2/arxiv_daily/data/feishu_preview_*.json。
本机的 .env 已经写入你的飞书 webhook（未提交），DEEPSEEK_API_KEY 还需要你填。

没有 DeepSeek key 时，可以先用离线模式跑通整条链路（不调用 LLM）：

    $env:PAPERBOT_SKIP_LLM="1"
    $env:TARGET_CATEGORYS="cs.IR"
    $env:MAX_PAPERS="3"
    $env:ARXIV_MAX_PAGES="1"
    $env:ARXIV_LOOKBACK_HOURS="168"
    python -m paperBotV2.arxiv_daily.arxiv
    cd paperBotV2\arxiv_daily
    python generate_arxiv_html.py

本地看 HTML：

    Copy-Item examples\sample_papers.json paperBotV2\arxiv_daily\data\20261101.json
    cd paperBotV2\arxiv_daily
    python generate_arxiv_html.py
    打开 output\arxiv_20261101.html

## 4. GitHub 配置

### 4.1 一键部署（和 paper-digest 的 deploy_github.py 类似）

先填好 .env 里的 FEISHU_URL 和 DEEPSEEK_API_KEY，然后：

    cd 项目根目录
    python deploy_arxiv.py --dry-run   # 只列文件、检查 .env，不联网
    python deploy_arxiv.py             # 隐藏输入 token，自动创建仓库/上传/写 Secrets/触发

token 权限：

    classic PAT：勾 repo + workflow
    fine-grained：Contents、Workflows、Secrets、Actions 读写

不要用 --token 明文传，会进入 shell history；直接运行脚本，按提示隐藏输入。
部署脚本不会上传 .env / .venv，也不会把 token 写进仓库。
部署完成后到 Settings -> Pages 选 gh-pages。

### 4.2 手动建仓库并推送

把整个目录推到 GitHub 仓库根目录，保证 .github/workflows 和 paperBotV2 在根目录。

### 4.3 添加 Repository Secrets

仓库 -> Settings -> Secrets and variables -> Actions -> New repository secret：

    FEISHU_URL          必填，飞书自定义机器人 webhook，多个群用英文逗号分隔
    DEEPSEEK_API_KEY    必填，DeepSeek API Key（sk-...）
    FEISHU_SECRET       可选，机器人开启签名校验时才需要

### 4.4 开启 GitHub Pages

仓库 -> Settings -> Pages -> Source 选 Deploy from a branch
分支选 gh-pages，目录选 /。
工作流第一次运行会自动创建 gh-pages 分支。

页面地址：

    https://<owner>.github.io/<repo>/arxiv_daily/

### 4.5 手动跑一次

仓库 -> Actions -> arxiv_daily_full -> Run workflow。

定时任务是 23 3 * * *（UTC），即北京时间 11:23。

## 5. 飞书机器人

1. 目标飞书群 -> 设置 -> 群机器人 -> 添加机器人 -> 自定义机器人
2. 复制 webhook，形如 https://open.feishu.cn/open-apis/bot/v2/hook/xxxxxxxx
3. 如果开启了签名校验，再复制 secret，填到 FEISHU_SECRET
4. webhook 填到 FEISHU_URL；多个群用逗号分隔

本版发送通用 interactive 卡片，不再依赖原作者私有的 template_id。
如果卡片字段在你的飞书版本上报错，可以把 feishu_sender.py 的 build_card
改成纯文本消息，最简单：

    {"msg_type":"text","content":{"text":"..."}}

## 6. DeepSeek

在 https://platform.deepseek.com/ 创建 API Key。
代码默认 model=deepseek-chat，OpenAI 兼容接口。
成本主要来自粗排 + 精排 + 翻译；如果太贵：

    降低 ARXIV_MAX_PAGES（默认 1，即每类 1 页）
    降低 RETURN_PAPERS（默认 20）
    只保留 cs.IR

## 7. 常用配置

在 workflow 的 env 里改：

    TARGET_CATEGORYS      默认 cs.IR,cs.CL,cs.CV
    MAX_PAPERS            默认 100（注意：这是每页大小，不是总量）
    ARXIV_MAX_PAGES       默认 1（每类最多抓 1 页，约 100 篇）
    ARXIV_LOOKBACK_HOURS  默认 36
    RETURN_PAPERS         默认 20
    ROUGH_SCORE_THRESHOLD 默认 4
    FEISHU_CHUNK_SIZE     默认 6（每张卡片论文数）

## 8. 本版修复了什么

1. P0 失败退出码
   原 workflow 的 if python ...; then ...; fi; exit_code=$? 在失败时拿到 0，
   会把失败当成功。已改成 python ... && { ...; exit 0; } || exit_code=$?。

2. P0 私有飞书模板
   原代码使用 template_id=AAqxH62u1uNko，只在作者飞书租户存在。
   本版新增 feishu_sender.py，使用通用卡片。

3. P0 工作流没有调用飞书发送
   原 workflow 只跑 arxiv.py 和 HTML，没有执行飞书发送脚本。
   本版新增 Send Feishu cards step。

4. P1 Python/actions/timeout
   升到 Python 3.11、checkout@v4、setup-python@v5（pip cache），
   timeout 改成 120 分钟，arXiv 请求间隔从 60s 降到 10s。

5. P1 重复发送
   feishu_sender.py 只读“今天”的 JSON，并写 .feishu_sent_YYYYMMDD 标记；
   手动重跑不会重复刷屏，--force 可强制重发。

6. P1 分片与失败处理
   每 6 篇一张卡片，避免飞书消息过大；发送失败会重试；
   最终失败时数据/HTML 仍会 commit，job 标红。

## 9. 常见问题

    FEISHU_URL is empty       GitHub secret 没配，去 Settings -> Secrets 添加
    invalid signature         机器人开了签名校验，FEISHU_SECRET 不对，或关掉签名
    飞书 code=19024/消息太长   把 FEISHU_CHUNK_SIZE 调小到 4
    今天没有推送              周末/节假日 arXiv 无更新，或没有过阈值论文
    openai 超时/429           DeepSeek 限流；重试，降低 MAX_PAPERS
    HTML 404                  Pages 没开，或分支不是 gh-pages
    static 模板缺失           确认仓库包含 output/static/

## 10. 简历写法

项目名：LLM4Paper：基于 LLM 排序与翻译的 arXiv 每日内容推荐系统

一句话：
GitHub Actions 定时抓取 cs.IR/CL/CV 论文，规则 + LLM 两级排序，
DeepSeek 翻译/摘要，飞书卡片推送，静态页归档；支持去重、分片、
失败重试与运行状态追踪。

想更偏搜广推，可以补：

    召回：分类 + 关键词 + 作者/机构 + 历史点击
    排序：粗排 + LLM 精排，离线评估 NDCG@10 / Precision@K
    反馈：飞书卡片加“有用/没用”，记录点击，做下一轮特征
    指标：每天 token 成本、P95 延迟、推送成功率、CTR

注意：arxiv_feishu_msg.py 现在是兼容 wrapper，实际调用 feishu_sender.py；
工作流直接使用 feishu_sender.py，不再依赖作者的私有模板。
