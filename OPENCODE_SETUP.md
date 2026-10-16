# Horizon 本地安装 + OpenCode API + GitHub Actions 自动发布

本说明记录本次本地化安装所做的配置与后续需要你手动完成的步骤。

## 1. 已完成的内容

| 项目 | 位置 | 说明 |
| --- | --- | --- |
| Horizon 源码 | `~/horizon` | 从 `Thysrael/Horizon@main` 拉取 |
| uv | `~/.local/bin/uv`（0.13.1） | 无 sudo 安装 |
| git | `~/.local/bin/git`（2.52.0） | 无 sudo，用 rpm 释放（包装脚本设置 `GIT_EXEC_PATH`） |
| Python 环境 | `~/horizon/.venv` | 固定 Python 3.12（3.15 下 `regex` 无 wheel 会编译失败） |
| 运行配置 | `data/config.json` | AI 使用 opencode 会话同款模型 |
| CI 配置 | `data/config.github.json` | 同上，供 Actions 使用 |
| 环境变量 | `.env`（已被 .gitignore 忽略） | `OPENCODE_API_KEY=public` |
| 定时工作流 | `.github/workflows/daily-summary.yml` | 每天 23:00 UTC 运行并发布到 gh-pages |
| 本地 git 仓库 | `~/horizon` | 已 `git init -b main` 并完成首次提交 |

### AI 配置（`ai` 段）

沿用当前 opencode 会话的模型设置：

```json
"ai": {
  "provider": "openai",
  "model": "deepseek-v4.1-flash-free",
  "base_url": "https://opencode.ai/inference/v1",
  "api_key_env": "OPENCODE_API_KEY",
  "languages": ["zh", "en"]
}
```

> Horizon 的 `api_key_env` 只能是**环境变量名**，密钥值放在 `.env`。因此本地 `.env` 里写的是
> `OPENCODE_API_KEY=public`（opencode 客户端使用的公开 key）。

## 2. 重要限制（务必阅读）

OpenCode 的**免费模型只能在 OpenCode 内部调用**。在 Horizon / CI 里直接 HTTP 调用会得到：

```
403 FreeTierError: OpenCode's free tier can only be used from within OpenCode.
```

本机实测确认该错误存在，因此当前配置**能让 Horizon 正常启动、抓取、加载配置，但 AI 打分/生成阶段会失败**。

要真正跑通，需要把 `OPENCODE_API_KEY` 换成**真实的 OpenCode Zen key**（在 https://opencode.ai/auth 获取），并把 `base_url` 改为官方网关：

```json
"base_url": "https://opencode.ai/zen/v1"
```

若暂时没有 Zen key，可改用其它有额度、OpenAI 兼容的 provider，例如 DeepSeek：

```json
"ai": {
  "provider": "deepseek",
  "model": "deepseek-chat",
  "base_url": "https://api.deepseek.com",
  "api_key_env": "DEEPSEEK_API_KEY"
}
```

## 3. 本地运行

```bash
cd ~/horizon
~/.local/bin/uv run horizon --hours 24          # 生成日报到 data/summaries/
~/.local/bin/uv run horizon --help              # 查看参数
~/.local/bin/uv run horizon-webhook --dry-run   # 预览 Webhook 内容
```

## 4. GitHub Actions 定时自动发布

工作流 `.github/workflows/daily-summary.yml` 每天 23:00 UTC（北京时间 07:00）运行，
`uv run horizon --hours 24` 生成日报，再用 `peaceiris/actions-gh-pages` 发布 `docs/` 到 `gh-pages` 分支。

### 需要你手动完成

1. **创建 GitHub 仓库并推送**（本机已初始化 git，但没有配置远程/凭据）：

   ```bash
   cd ~/horizon
   git remote add origin git@github.com:<你的用户名>/<仓库名>.git
   git push -u origin main
   ```

2. **配置仓库 Secret**：仓库 → Settings → Secrets and variables → Actions → New repository secret
   - `OPENCODE_API_KEY` = 你的真实 OpenCode Zen key（或改用其它 provider 对应的 key，如 `DEEPSEEK_API_KEY`）
   - 可选：`HORIZON_WEBHOOK_URL`（飞书/钉钉/Slack 通知）、`LWN_KEY`、`GITHUB_TOKEN` 无需手动配置

3. **开启 GitHub Pages**：仓库 → Settings → Pages → Build and deployment → Source 选
   **Deploy from a branch** → 分支选 `gh-pages` / 根目录。之后首次运行工作流即可访问站点。

4. **首次运行**：仓库 → Actions → Daily Horizon Summary → Run workflow（手动触发一次验证）。

### 说明

- 工作流会先执行 `cp data/config.github.json data/config.json`，因此 **CI 用的是 `data/config.github.json`**。
  若要调整 CI 行为（例如换 provider），改这个文件。
- 仓库自带的 `deploy-docs.yml` 只在 push 到 `main` 且改动 `docs/**` 时触发，与本工作流不冲突（都发布到 `gh-pages`）。
- `data/config.json`、`.env` 已在 `.gitignore` 中，不会被提交。

## 5. 相关文件清单

- `data/config.json`：本地运行配置（AI 使用 opencode）
- `data/config.github.json`：CI 运行配置
- `.env`：本地密钥（`OPENCODE_API_KEY=public`）
- `.github/workflows/daily-summary.yml`：定时自动化工作流
