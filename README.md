# hermes-bot-chat-rotation

一个 [Hermes Agent](https://hermes-agent.nousresearch.com/docs/) **技能（skill）**：轮换 bot 的主对话。

Bot Mode 下每个 bot 就是一个 Hermes profile，它的主对话是**标题正好为 `Bot Chat`** 的那条会话（每个 profile 一条，没有会话 id 指针）。
本技能把当前这条退休，并新开一条**第一件事就是读完旧对话**的主对话——新对话带着上下文开始，而不是失忆重来。

## 它做什么

对每个 bot（或你指定的那几个）：

1. **归档**当前 `Bot Chat`（`session.archive`）——消息全部保留，会话退休。归档行仍留有历史，但让出了名字，
   此后**只能按会话 id** 找到它。
2. **新建一条同名 `Bot Chat`**（`session.create`，标题正好 `Bot Chat`、born hidden、跟随该 profile 自身配置），
   并立刻落标题，保证注册表里 `Bot Chat` 永远只有一行。
3. **投一句开场指令**：让新对话读取已归档的那条（`session_search(session_id="<旧 id>")`），写一份简短承接记录，再往下走。

全程走**桌面后端的 JSON-RPC**（`hermes serve`，也就是 Bots 面板点击用的同一条通道），所以新会话是真正的桌面 Bot Chat，
不是 one-shot CLI 会话——后者不会成为 bot 的主对话。

## 安装

把这个目录拷进某个 profile 的 skills 目录。**profiles 之间互不继承**，要让多个 bot 都能用就逐个拷：

```bash
cp -r hermes-bot-chat-rotation ~/.hermes/profiles/<bot>/skills/autonomous-ai-agents/
# Windows 默认安装：%LOCALAPPDATA%\hermes\profiles\<bot>\skills\autonomous-ai-agents\
```

## 前提

- 同一台机器上跑着 Hermes 后端：桌面应用，或任何 `hermes serve` 进程（脚本只连 `127.0.0.1`）。
- Python 带 `websockets`。用普通 `python` 跑也可以——缺 `websockets` 时脚本会自己 re-exec 到 Hermes venv 的 Python。
- 探测失灵时可覆盖：`HERMES_PYTHON`、`HERMES_DESKTOP_URL`、`HERMES_SESSION_TOKEN`。

## 用法

```bash
python scripts/rotate_bot_chats.py --dry-run         # 先看会动哪些 bot
python scripts/rotate_bot_chats.py                   # 本机全部 profile
python scripts/rotate_bot_chats.py research steward  # 只动这几个 profile
python scripts/rotate_bot_chats.py --no-prompt       # 只归档 + 建新，不投开场句
```

跑完脚本自己打印核验：RPC 侧（按标题查 `session.list`、`profiles.list` 的 canonical 会话）+
找得到 `state.db` 时再直读两行（旧行 `archived=1, title NULL`；新行 `title='Bot Chat', hidden=1, source='desktop'`）。

开场指令模板在脚本顶部的 `OPENING`——要改语言或承接记录的格式，改那里，不用改技能正文。

## 也就是一个标准 Hermes skill

`SKILL.md` 是标准的 Hermes 技能文件：把这个目录放进你的 skills 目录，用户在对话里说「轮换 bot 主对话」时 agent 就会加载它。
本仓库就是这个技能，只是单独发布。

## 许可

MIT，见 [LICENSE](LICENSE)。
