# Horizon 本地安装 + OpenRouter + GitHub Actions 自动发布

本说明记录本次本地化安装所做的配置与后续需要你手动完成的步骤。

## 1. 已完成的内容

| 项目 | 位置 | 说明 |
| --- | --- | --- |
| Horizon 源码 | `~/horizon` | 从 `Thysrael/Horizon@main` 拉取 |
| uv | `~/.local/bin/uv`（0.13.1） | 无 sudo 安装 |
| git | `~/.local/bin/git`（2.52.0） | 无 sudo，用 rpm 释放（包装脚本设置 `GIT_EXEC_PATH`） |
| Python 环境 | `~/horizon/.venv` | 固定 Python 3.12（3.15 下 `regex` 无 wheel 会编译失败） |
| 运行配置 | `data/config.json` | AI 使用 OpenRouter |
| CI 配置 | `data/config.github.json` | 同上，供 Actions 使用 |
| 环境变量 | `.env`（已被 .gitignore 忽略） | `OPENROUTER_API_KEY=...` |
| 定时工作流 | `.github/workflows/daily-summary.yml` | 每天 23:00 UTC 运行并发布到 gh-pages |
| 本地 git 仓库 | `~/horizon` | 已 `git init -b main` 并完成提交 |

### AI 配置（`ai` 段）

```json
"ai": {
  "provider": "openai",
  "model": "${HORIZON_AI_MODEL}",
  "base_url": "https://openrouter.ai/api/v1",
  "api_key_env": "OPENROUTER_API_KEY",
  "languages": ["zh", "en"]
}
```

OpenRouter 是 OpenAI 兼容网关，因此 `provider` 用 `openai`。密钥与模型都放在 `.env`：

```
OPENROUTER_API_KEY=sk-or-v1-...
HORIZON_AI_MODEL=google/gemini-2.5-flash-lite
```

`config.json` 里任何字符串都支持 `${VAR}` 引用环境变量；`main.py` 启动时会自动加载仓库根目录的 `.env`。
（Horizon 的 `api_key_env` 只能是环境变量名，不能直接写密钥值。）

想换模型只需改 `.env` 的 `HORIZON_AI_MODEL`（无需改 JSON），例如：

| 模型 | 说明 |
| --- | --- |
| `google/gemini-2.5-flash-lite` | 当前使用；便宜快速（$0.1/M in，$0.4/M out） |
| `deepseek/deepseek-chat` | 极便宜，JSON 输出稳定 |
| `google/gemini-2.5-flash` | 质量更高（$0.3/M in，$2.5/M out） |
| `nvidia/nemotron-3.5-lightning:free` | 免费，需实测 JSON 模式兼容性 |

> 注意：Horizon 会向模型发送 `response_format: {"type": "json_object"}`。请选择支持
> JSON 模式的模型，否则打分/生成会失败。

## 2. 本地运行

```bash
cd ~/horizon
~/.local/bin/uv run horizon --hours 24          # 生成日报到 data/summaries/
~/.local/bin/uv run horizon --help              # 查看参数
~/.local/bin/uv run horizon-webhook --dry-run   # 预览 Webhook 内容
```

## 3. GitHub Actions 定时自动发布

工作流 `.github/workflows/daily-summary.yml` 每天 23:00 UTC（北京时间 07:00）运行，
`uv run horizon --hours 24` 生成日报，再用 `peaceiris/actions-gh-pages` 发布 `docs/` 到 `gh-pages` 分支。

### 需要你手动完成

1. **创建 GitHub 仓库并推送**（本机已初始化 git，但没有配置远程/凭据）：

   ```bash
   cd ~/horizon
   git remote add origin git@github.com:<你的用户名>/<仓库名>.git
   git push -u origin main
   ```

2. **配置仓库 Secret / Variable**：仓库 → Settings → Secrets and variables → Actions
   - Secret `OPENROUTER_API_KEY` = 你的 OpenRouter API key（https://openrouter.ai/keys）
   - Variable（可选）`HORIZON_AI_MODEL` = 模型 id；不设置则工作流回退到默认
     `google/gemini-2.5-flash-lite`
   - 可选：Secret `HORIZON_WEBHOOK_URL`（飞书/钉钉/Slack 通知）、`LWN_KEY`

3. **开启 GitHub Pages**：仓库 → Settings → Pages → Build and deployment → Source 选
   **Deploy from a branch** → 分支选 `gh-pages` / 根目录。之后首次运行工作流即可访问站点。

4. **首次运行**：仓库 → Actions → Daily Horizon Summary → Run workflow（手动触发一次验证）。

### 说明

- 工作流会先执行 `cp data/config.github.json data/config.json`，因此 **CI 用的是 `data/config.github.json`**。
  该文件的模型同样写作 `${HORIZON_AI_MODEL}`，由工作流的 `env` 注入（默认回退 `google/gemini-2.5-flash-lite`）。
- 仓库自带的 `deploy-docs.yml` 只在 push 到 `main` 且改动 `docs/**` 时触发，与本工作流不冲突（都发布到 `gh-pages`）。
- `data/config.json`、`.env` 已在 `.gitignore` 中，不会被提交。

## 4. 相关文件清单

- `data/config.json`：本地运行配置（AI 使用 OpenRouter）
- `data/config.github.json`：CI 运行配置
- `.env`：本地密钥与模型（`OPENROUTER_API_KEY=...`、`HORIZON_AI_MODEL=...`）
- `.github/workflows/daily-summary.yml`：定时自动化工作流
