# OpenCodeBridge

**发封邮件即让电脑免费干活！**

OpenCodeBridge 是一款基于 PyQt6 的桌面看门狗工具，持续监控指定邮箱的收件箱，匹配特定发件人或命令前缀的邮件，将内容提取为任务指令并发送给本地运行的 OpenCode AI 编码代理（serve 模式）执行，最后将执行结果实时展示在 GUI 日志面板，并可选通过 SMTP 邮件回复给发件人。

## 适用场景

- 在手机或任何设备上通过邮件远程触发 AI 编程任务，无需打开电脑终端
- 团队协作：成员通过邮件发送指令，由 OpenCode AI 自动处理文件操作、代码生成、数据分析等
- 与自动化工作流集成：其它系统可发邮件给 OpenCodeBridge 触发 AI 任务，结果自动回复

## 工作原理

```
发件人邮件 → IMAP 轮询 → 解析命令 → OpenCode serve API → AI 模型执行 → GUI 日志
                                                                   ↓ (可选)
                                                          SMTP 回复邮件给发件人
```

1. **IMAP 轮询** — 按设定的间隔（默认 5 秒）检查收件箱，匹配发件人地址和命令前缀（如 `/task`）
2. **命令提取** — 从邮件主题或正文中提取命令文本，支持多行命令
3. **AI 执行** — 通过 HTTP API 发送给本地 `opencode serve` 服务，由 AI 模型（默认 Zen 免费模型）执行
4. **结果展示** — 执行结果实时输出到 GUI 彩色日志面板，含时间戳和状态标识
5. **邮件回复** — （可选）自动将结果通过 SMTP 回复给发件人，支持携带附件

## 功能特性

- **系统托盘** — 点击关闭按钮自动隐藏到系统托盘，后台持续运行，双击托盘图标恢复窗口
- **开机自启** — 在配置面板勾选"开机自动启动"，自动写入 Windows 注册表 Run 键
- **自动检测** — 启动时自动扫描本地 opencode serve 服务（端口 4096），支持自动启动 CLI
- **多线程架构** — 邮件监控在独立线程运行，命令执行不阻塞 GUI，支持命令队列串行处理
- **彩色日志** — 按级别（信息/成功/警告/错误）着色显示，带时间戳、可清空
- **智能附件** — 自动检测 AI 回复中引用的文件路径和最近的临时文件，作为邮件附件回复
- **安全配置** — 配置文件 `.gitignore` 保护避免误提交，支持授权码模式登录

## 快速开始

### 安装依赖

```bash
pip install -r requirements.txt
```

### 配置邮箱

启动程序后，在 GUI 的「配置」页填写以下信息：

**邮箱监控配置**

| 字段 | 说明 | 示例 |
|---|---|---|
| 被监控发件人 | 只处理此发件人的邮件，留空则不限制 | `user@example.com` |
| 主题前缀 | 命令触发前缀，留空则处理全部邮件 | `/task` |
| 轮询间隔 | 检查新邮件的间隔（2~120 秒） | `5` 秒 |
| IMAP 服务器 | 邮箱的 IMAP 地址 | `imap.qq.com` |
| IMAP 端口 | 一般使用 SSL 993 | `993` |
| 邮箱账号 | 完整的邮箱地址 | `user@example.com` |
| IMAP 授权码 | QQ/163 邮箱需使用授权码（非登录密码） | |

**SMTP 回复邮件（可选）**

| 字段 | 说明 | 示例 |
|---|---|---|
| SMTP 服务器 | 邮箱的 SMTP 地址 | `smtp.qq.com` |
| SMTP 端口 | SSL 465 或 TLS 587 | `465` |
| SMTP 账号 | 留空则使用 IMAP 账号 | |
| SMTP 授权码 | 留空则使用 IMAP 授权码 | |
| 发件人地址 | 显示在回复邮件中的 From | `user@example.com` |

**OpenWork / OpenCode 连接**

| 字段 | 说明 |
|---|---|
| 服务器 URL | 留空则自动通过 opencode CLI 发送 |
| Workspace ID | 可选，OpenCode 工作空间 ID |
| Token | 可选，Bearer Token |

点击 **保存配置** 持久化所有设置，然后点击 **启动监控** 开始轮询。

### 邮件格式

邮件主题或正文以 `/task` 开头，后面的内容将作为命令发送给 AI：

```
/task 请打开D盘根目录，列出所有文件夹
```

也可以 `/task` 单独一行，下一行为命令正文：

```
/task
请编写一个 Python 脚本，读取当前目录下的 CSV 文件并统计每列的平均值
```

如果没有配置前缀，则整封邮件正文作为命令处理。

### 运行

```bash
python main.py
```

程序启动后会自动检测本地是否已有 `opencode serve` 进程（扫描端口 4096），如果安装了 opencode CLI 但未运行，会自动启动服务。

### 配置文件

复制 `config.example.json` 为 `config.json` 并填写实际配置：

```bash
copy config.example.json config.json
```

`config.json` 已被 `.gitignore` 排除，不会提交到仓库。

## 技术栈

- **Python 3.12+**
- **PyQt6** — GUI 界面（主窗口、配置表单、彩色日志、系统托盘）
- **imaplib** — IMAP 邮件接收（Python 标准库，零外部依赖）
- **smtplib** — SMTP 邮件发送（Python 标准库，零外部依赖）
- **httpx** — HTTP API 客户端（连接 OpenCode serve）
- **OpenCode Zen** — 免费 AI 模型（`opencode/deepseek-v4-flash-free`）
- **threading / concurrent.futures** — 多线程任务管理与超时控制

## 项目结构

```
OpenCodeBridge/
├── main.py                       # 入口：启动 QApplication
├── requirements.txt              # Python 依赖
├── config.json                   # 本地配置文件（已 gitignore）
├── config.example.json           # 配置模板（不含敏感信息）
├── test_regex.py                 # 路径提取正则辅助测试
│
├── opencode_bridge/
│   ├── app.py                    # QApplication 引导、窗口居中
│   │
│   ├── config/
│   │   └── settings.py           # AppConfig 数据类、JSON 序列化、注册表自启
│   │
│   ├── gui/
│   │   ├── main_window.py        # 主窗口：系统托盘、命令队列、监控启停
│   │   ├── settings_panel.py     # 配置面板：IMAP / SMTP / OpenCode 表单
│   │   └── log_panel.py          # 彩色日志面板：多级别着色、时间戳
│   │
│   ├── monitor/
│   │   ├── email_monitor.py      # 邮件监控线程：IMAP IDLE 轮询、新邮件检测
│   │   ├── email_sender.py       # 邮件发送工具：SMTP 连接测试、附件支持
│   │   └── message_parser.py     # 消息解析：命令提取、发件人识别
│   │
│   └── openwork/
│       └── client.py             # OpenCode API 客户端：服务扫描、prompt 发送
```

## 开发指南

```bash
# 创建虚拟环境
python -m venv venv
venv\Scripts\activate

# 安装开发依赖
pip install -r requirements.txt

# 运行
python main.py
```

## 开源协议

MIT
