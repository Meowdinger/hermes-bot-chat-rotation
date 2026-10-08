---
name: bot-chat-rotation
description: "归档 bot 的主对话，另开一条会读旧对话的新主对话。"
version: 0.1.0
author: meowdinger, Hermes Agent
license: MIT
platforms: [windows, macos, linux]
metadata:
  hermes:
    tags: [Bot-Mode, Session, Rotation, Handoff]
    category: autonomous-ai-agents
---

# Bot 主对话轮换

把 bot 的主对话（Bot Chat）归档，另建一条同名的新的，并让新的第一件事就是读完旧的。走桌面后端，与 Bots 面板点击同一条路。

## When to Use

- 「把所有 bot 的主对话归档，开新的读旧的」「bot chat 轮换 / 重建 / 重开一条」。
- 某条线的主对话压满了，要换一条干净的接着跑。
- 不是这个：单会话 `/compact`（不换会话）、普通会话归档（右键归档即可）。

## 本质

- **默认只动脚本自己所在的 profile**（发给哪个 bot，就重置哪个）。每个 bot 的 skills 目录各有一份脚本，不带参数运行时目标就是它自己（HERMES_HOME，回退看安装路径）；全机轮换必须显式 `--all`。
- **Bot Chat 的身份 = (profile, 标题正好是 `Bot Chat`)**，没有 id 指针。用 `session.create {title:'Bot Chat', hidden:true, follow_profile_config:true}` 建，随后 `session.title` 立刻落标题——行是懒建的，不落标题就会开出第二条。
- **顺序：先归档旧行，再给新行落标题。** 标题事务会把「已归档且 hidden」的旧行 title 置 NULL，注册名让给新行。所以归档后旧对话**只能按 id 读，按标题已找不到**——承接指令里必须写 id。
- **新会话的第一句就是承接指令**（`session_search(session_id=<旧 id>)`）。不投这句，新主对话就是空的。
- 桌面后端 = Electron 起的 `hermes serve`，端口与 token 每次现取。**`hermes -p X chat -q` 不算**：它建的会话不是 Bot Chat，点 bot 不会落到它上面。

## 跑

```bash
# 用 Hermes venv 的 python 最好；系统 python 直接跑也行——脚本自己 re-exec 到 venv，找不到才报错。
python "<skill>/scripts/rotate_bot_chats.py" --dry-run         # 先看会动谁（默认：本 profile）
python "<skill>/scripts/rotate_bot_chats.py"                   # 轮换本 profile——发给哪个 bot 就重置哪个
python "<skill>/scripts/rotate_bot_chats.py" research steward  # 指定 profile
python "<skill>/scripts/rotate_bot_chats.py" --all             # 本机全部（显式全量）
```

脚本一条龙：找后端端口/token → `profiles.list` 取各 profile 的 `canonical_session` → `session.archive` → `session.create` → `session.title` → 回读 state.db（找得到就读，找不到只给 RPC 侧）核验 → `prompt.submit` 首句承接指令。首句模板在脚本顶部 `OPENING`，要改承接要求就改它。

## 装到别的机器 / 别的 bot

- 把整个 `bot-chat-rotation/` 目录拷到目标机任意 profile 的 `skills/<category>/` 下就能用；**profiles 互不继承**，要每个 bot 都能用就逐 profile 拷一份。
- 目标机前提：桌面应用（或任何 `hermes serve` 后端）在跑、脚本能连上它的 127.0.0.1 WS。脚本不写死 profile 名、端口、路径：bot 名单来自后端 roster，端口自己探；`HERMES_PYTHON` / `HERMES_DESKTOP_URL` / `HERMES_SESSION_TOKEN` 可覆盖探测结果。
- 后端在别的机器（SSH / 远程 connection）时，脚本要在**那台机器上**跑——它只走 127.0.0.1。

## 核验（不信 ACK）

脚本跑完自己打印核验：RPC 侧看 `session.list {title:'Bot Chat', include_hidden:true}` 只剩新行、`profiles.list.canonical_session` 指向新 id；本机找得到 state.db 就再直读两行（旧行 `archived=1 / hidden=1 / title IS NULL`，新行 `title='Bot Chat' / hidden=1 / source='desktop'`）。读取进度看新行 `messages` 增长与 `session_turn_leases`（有 lease 才是在跑）——turn 由桌面后端持有，脚本断开也照跑。

## 坑

- 动手前查 `session_turn_leases`：忙会话会被 `prompt.submit` 打断当前回合。
- WS 连接必须 `max_size=None`（服务端重放 `gateway.ready` 大帧，默认 1MB 上限会打死连接）。
- `prompt.submit` 用**运行态** session_id（`session.create` 返回的短 hex），存储 id 会 4001。
- 旧行标题被置空是**预期**行为，不是丢数据：消息全在，按 id 读得到。
- 回退：`session.archive {archived:false}` 解归档；要让旧行拿回 `Bot Chat` 标题，得先让新行让位。
- 只动 `Bot Chat`，不碰别的会话；不手改 state.db。
