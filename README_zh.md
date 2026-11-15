# Social GTM Concierge（活动 AI 接待员）

为 **Social GTM Agents Hackathon**（swanbase × Zernio，巴黎，2026-11-15）做的 AI agent，基于 [Zernio](https://zernio.com) 社交 API 和 [Claude](https://www.anthropic.com)，帮活动主办方在社交媒体上做增长（GTM）。

主办方在现场走动，把每支队伍的照片发给 Telegram 机器人，并转述几轮提问。agent 把每次采访写成 Instagram 帖子，通过 Zernio 发布；之后有人评论或私信，它会推荐最相关的项目、根据采访内容答疑、帮人引荐给队伍，并引导到主办方的下一场活动。

English version: [README.md](README.md).

## 工作流程

1. **采访（Telegram）**：发队伍照片并配一句话介绍。Claude 一次问一个问题（最多 5 个，`/done` 可提前结束），风格可设置；最后会问队伍的联系方式，以及是否愿意公开。
2. **起草与发布**：Claude 写好文案和结构化记录，你用 ✅ Publish / ✏️ Rewrite / 🗑 Drop 审核；点 Publish 就通过 Zernio 发到 Instagram。
3. **互动（Instagram）**：有人评论时，agent 公开回复，并发一条个性化私信，推荐 2 个最相关的项目。之后的私信对话只根据已发布的采访来回答，对话历史从 Zernio 收件箱读取。
4. **转化**：给对方推荐主办方的下一步（可配置，到期自动下线）。队伍的公开联系方式从数据库原样发出；不公开的队伍走引荐流程，引荐请求通过 Telegram 通知主办方。
5. **展示**：本机的实时 dashboard 显示队伍、实时动态、兴趣分布，以及“评论到私信”的耗时。

## 防护措施

- **有据可查**：只依据已发布的采访和 `concierge/event_info.py` 回答，所有 Claude 调用都用结构化输出。
- **链接白名单**：发送前由代码删掉不在白名单里的链接（白名单只有已发布帖子和配置好的活动链接）；同一个链接对同一个人只发一次。
- **联系方式**：必须包含真实的邮箱、链接、@用户名或电话才会保存和分享；提问者的联系方式必须是本人亲手打出来的，才会保存。
- **防循环**：重复消息和带机器人标记的消息（`[echo]`、`auto-reply:` 等）不回复。
- **上限**：每人每天最多 30 条自动回复；对方说“找真人”时，暂停对这个人的自动回复（用 `/resume` 交还给机器人）。
- **Webhook**：HMAC 签名校验，事件去重。
- **隐私**：dashboard 只能在本机访问，用户名缩写显示，不显示联系方式；Telegram 只有操作者和被批准的队友能用。

## 环境要求

- macOS 或 Linux，安装 [uv](https://docs.astral.sh/uv/)（会自动装好指定版本的 Python）和 cloudflared（`brew install cloudflared`）
- Zernio 账号，并连接一个 Instagram **商业号或创作者号**（Instagram 登录方式即可），外加 Zernio API key
- 从 [@BotFather](https://t.me/BotFather) 获取的 Telegram 机器人 token
- Anthropic API key

## 安装

```bash
git clone https://github.com/mehditebib00-prog/hackaton-agent-swanbase-zernio-.git
cd hackaton-agent-swanbase-zernio-
uv sync
cp .env.example .env                       # 然后填写下表中的值
uv run python -m probe.setup gen-secret    # 生成 ZERNIO_WEBHOOK_SECRET 并写入 .env
```

| 变量 | 必填 | 说明 |
|---|---|---|
| `ZERNIO_API_KEY` | 是 | Zernio API key |
| `ZERNIO_WEBHOOK_SECRET` | 是 | Zernio 给 webhook 签名用的随机字符串（`gen-secret` 自动生成） |
| `ZERNIO_IG_ACCOUNT_ID` | 否 | 指定用哪个 Instagram 账号，默认用第一个已连接的 |
| `TELEGRAM_BOT_TOKEN` | 是 | @BotFather 给的 token |
| `TELEGRAM_OWNER_ID` | 否 | 固定操作者；不填则第一个发 `/start` 的人成为操作者 |
| `ANTHROPIC_API_KEY` | 是 | Claude API key |

`.env` 里的值会覆盖 shell 里已有的同名变量。不要提交 `.env`。

换一场活动时，只需改 `concierge/event_info.py` 里的 `EVENT`、`CTAS`、`STYLE_PRESETS`，不用改其他代码。

## 启动

```bash
uv run python -m concierge.run          # 一条命令启动服务 + 隧道 + webhook（Ctrl-C 停止）
uv run python -m concierge.run --stop   # 停掉残留的进程
```

脚本会依次：在 `:8000` 启动服务 → 打开 cloudflared 隧道 → 等公网地址能访问 → 把 Zernio webhook 指向新地址（没有就新建）→ 发测试事件 → 等 Telegram 机器人连上。临时隧道的地址每次启动都会变，脚本每次都会自动更新 webhook。日志在 `data/app.log` 和 `data/tunnel.log`。

Dashboard：<http://localhost:8000/dashboard>（只能在本机打开）。

## Telegram 命令

| 命令 | 谁能用 | 作用 |
|---|---|---|
| `/start` | 任何人 | 第一个人成为操作者；其他人发起权限申请 |
| `/allow <id>` | 操作者 | 批准队友采访和发布 |
| （照片 + 说明） | 成员 | 开始一次采访 |
| `/done` | 成员 | 提前结束提问并起草 |
| `/style [预设或描述]` | 成员 | 设置采访风格：journalist、casual、investor、storyteller，或自定义 |
| `/contact [id] [联系方式\|none]` | 成员 | 查看队伍列表，或设置/清除某队伍的公开联系方式 |
| `/recap` | 成员 | 生成照片拼图和当天的汇总帖 |
| `/stats` · `/export` | 成员 | 互动概况 · 导出采访、线索、引荐的 CSV（仅限私聊） |
| `/resume <ig 用户名>` | 成员 | 把对话交还给机器人 |
| `/cancel` | 成员 | 清空当前采访 |

## 数据

运行时数据都在 `data/`（已被 git 忽略）：SQLite 数据库、队伍照片和日志。里面有别人的照片、用户名和联系方式，不要外传；删除这个目录就能重置活动。

## 测试

```bash
uv run pytest
```
