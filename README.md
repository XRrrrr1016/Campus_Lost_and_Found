# 校园拾光 · 校园失物招领与智能匹配系统

**选题：T03，题目 3。** 技术栈：Python 3.11+ 标准库、SQLite、HTML/CSS/原生 JavaScript。前后端通过 HTTP JSON 通信，运行无需第三方依赖、无需 AI 密钥、无需付费服务。

已实现：失物/招领发布、可选图片、组合筛选、预置账号与角色权限、候选匹配及解释、私密特征认领核验、联系方式保护、交接结案、软删除和审计、管理员字段权重与规则版本、历史推荐快照复算、业务自动测试和 12 组 AI 评测。

**未完成交付项：真实开发全程录屏与最终演示视频未附带。** 已提供真实缺失说明、索引及演示脚本，不能用截图或补录假装此前的开发过程。候选人编号未提供，打包时须填写。未实现可选进阶的图像匹配、举报、重复发布检测；只做本地演示，不包含生产身份认证。

## 启动

安装 Python 3.11 或更高版本（本项目实际验证为 Python 3.12）。进入当前目录：

```powershell
python --version
python app.py
```

首次启动自动创建 `data/campus.sqlite3`、3 个演示账号、8 条样例及基础规则。浏览器打开 **http://127.0.0.1:8000**。Windows 可双击 `start.cmd`，或运行 `powershell -File start.ps1`。关闭终端或按 Ctrl+C 停止；重新启动保留已有数据，初始化不会重复添加样例。

```powershell
# 可选：先幂等初始化
python app.py --init-only
# 端口被占用时
python app.py --port 8001
# 使用独立的新数据库，保留原有数据
python app.py --db data/fresh.sqlite3 --no-seed
```

无需 `pip install`、`npm install` 或前端构建。配置见 `config.example`；它是说明文件，不会被自动读取。支持 `CAMPUS_HOST`、`CAMPUS_PORT`、`CAMPUS_DB` 环境变量，命令行参数优先。只允许本地 `127.0.0.1` / `localhost`；浏览器必须带实际端口访问。

## 演示账号与闭环

界面右上角“登录账号/切换账号”使用以下本地预置账号。两个普通账号均可以发布失物或招领，角色由具体行为决定。

| 账号 | 密码 | 身份及操作 |
| --- | --- | --- |
| `alice` | `demo1234` | 林同学：失物发布、匹配、提交认领 |
| `bob` | `demo1234` | 陈同学：招领发布、核验、交接 |
| `admin` | `admin1234` | 管理员：所有核验、规则发布、审计 |

1. 访客查看广场，组合使用关键词/类别/地点/日期/状态。联系方式不可见。
2. 切换林同学 → 我的发布 → “在图书馆遗失黑色卡包” → 智能匹配。
3. 查看“图书馆捡到一个黑色卡包”，阅读匹配依据，申请认领。演示核验答案为 **向阳**，可关联自己的卡包失物，填写联系方式。
4. 切换陈同学 → 认领与交接 → 查看私密特征核验标志 → 核验通过。此时向双方开放联系方式，相关记录变为待交接。
5. 交接后由陈同学或管理员“已交接，确认结案”。招领、关联失物和申请同时更新状态。
6. 切换管理员 → 规则与审计 → 修改字段权重（0 表示禁用）→ 发布新版本。查看核验、驳回、结案等审计。
7. 切换林同学 → 智能匹配 → 推荐历史与复算。规则改变、原物品结案或删除后，原批次仍用旧规则和输入快照精确复算。

其他样例招领的私密答案为“小太阳”。这些答案仅用于虚构样例验收；真实发布时应自行设置、不写入公开文字或图片。系统会拒绝直接出现在公开文本中的答案，但无法自动识别图片泄密或现实身份。

异常演示：用错误答案申请另一件招领，拾获者只能驳回；未登录不能发布，普通用户不能改规则、核验他人发布；同一用户不能重复认领同一记录。删除开放记录需填写原因，保留中的记录必须先交接。

## 测试与 AI 演示

```powershell
python -m unittest discover -s tests -v
python scripts/evaluate_ai.py
# 需要留存最新评测数据时
python scripts/evaluate_ai.py --output docs/ai-evaluation.json
```

AI 使用**可复现的离线文本匹配模拟接口**，不是远程大模型。字符二元组 Dice 相似度、地点/颜色同义词、类别和时间范围构成加权得分，再生成基于字段的自然语言依据。无网络、无密钥时行为相同，无需额外降级开关。少于三个有效字段时标记“信息不足”，字段冲突压低得分；始终需要核验未公开特征。详见 [架构与算法](docs/03-architecture.md)、[测试报告](docs/06-test-report.md)。

可选浏览器回归需要 Node.js 和开发测试依赖 `playwright`（仅测试工具，不是运行依赖）：

```powershell
npm install --no-save --package-lock=false playwright
# Windows 默认复用系统 Chrome；也可设置 $env:BROWSER_EXECUTABLE 为浏览器路径。
node tests/browser_smoke.cjs
# 未安装 Chrome 的平台可先 npx playwright install chromium。
```

此回归使用独立临时数据库，覆盖发布/图片/筛选/匹配/核验/交接/规则/复算和手机布局；截图在 `output/qa/`。`PLAYWRIGHT_MODULE` 可指向已有 Playwright 模块，`PYTHON` 可选择 Python 可执行文件。常规验收只需前面的 Python 测试。

## 结构与交付

```text
app.py                 启动与配置
src/server.py          HTTP、会话、CSRF、统一错误及静态资源
src/service.py         权限、认领事务、隐私、规则与推荐快照
src/database.py        SQLite 表结构及幂等初始化/增量升级
src/matching.py        确定性离线匹配引擎
src/static/            前端
tests/                 业务、HTTP 集成、AI 评测与浏览器回归
scripts/               评测与源码打包
docs/                  spec、plan、架构、决策、AI 协作、测试、录屏索引
recordings/            真实录屏存放说明（当前未附视频）
```

```powershell
python scripts/package.py --candidate-id 你的候选人编号
# 可选：独立解压、两次初始化并运行全部 Python 测试与 AI 评测
python scripts/verify_package.py output/你的候选人编号_T03_失物招领.zip
```

压缩包生成于 `output/编号_T03_失物招领.zip`，内部根目录同名。不填写编号时明确使用“待填写编号”，不能原样作为正式编号提交。白名单仅收录源码、样例、文档、配置和脚本；排除数据库、依赖目录、虚拟环境、缓存、输入 PDF、截图和视频。录屏按招聘方要求单独上传或手工加入，索引须填真实访问方式。

## 运行边界与来源

- 会话是服务端保存的随机令牌，cookie 为 HttpOnly/SameSite=Strict；修改接口校验 CSRF/Origin/Host。演示 cookie 使用本地 HTTP，未配置生产 HTTPS。
- SQLite 写事务串行化，核心状态更新、关联结案、自动驳回和审计原子提交；删除为软删除。
- 图片只支持 500KB 内 PNG/JPEG/WebP，存储为 data URL，只展示不参加匹配。仅作文件签名检查，没有完整图像解码或恶意内容扫描。
- 默认列表上限 500 条；未实现分页、大规模检索压测、注册/找回密码、登录限流或真实身份校验。请勿用于真实校园公开服务。
- 应用代码及 CSS 装饰在本次 AI 协作中编写，没有复用外部完整项目、模板或图片。Python/SQLite 为运行环境；可选 Playwright 仅用于开发测试，许可证 Apache-2.0，来源 https://github.com/microsoft/playwright 。未调用第三方 AI 服务。
- AI 参与过程和候选人仍需完成的人工复核见 [AI 协作记录](docs/05-ai-collaboration.md)，录屏缺失见 [录屏索引](docs/recording-index.md)。
