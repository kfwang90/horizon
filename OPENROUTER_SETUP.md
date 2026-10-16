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

## 3. GitHub Actions 定时自动发布（并入现有 Hexo 站点）

目标仓库 `kfwang90/kfwang90.github.io` 是一个 **Hexo 博客**，用 GitHub Actions 部署
（`.github/workflows/static.yml`：`hexo generate` → `public/` → `deploy-pages`），
Pages 的 Source 是 **GitHub Actions**，并非 "Deploy from a branch"。

> **第 4 步不需要改。** 但接入方式也不同：不能推 `gh-pages` 分支（Actions 源不读分支内容），
> 而要把**预构建好的静态文件**推到 Hexo 仓库的 `source/horizon/`，由 Hexo `generate` 原样拷入
> `public/horizon/`，再交给你现有的工作流部署。

工作流 `.github/workflows/daily-summary.yml` 每天 23:00 UTC（北京时间 07:00）运行：

```
生成日报 → CI 内 jekyll build 把 docs/ 编译成静态 HTML → 推送到 kfwang90.github.io 的 source/horizon/（main）
        → 触发 Hexo 工作流（hexo generate → public/）→ GitHub Pages 部署
```

最终地址：`https://kfwang90.github.io/horizon/`

> **为什么要预构建**：`docs/` 本身是 Jekyll 站点（`_config.yml` + `_posts` + 远程主题）。
> Hexo 只会把 `source/` 里的非渲染文件当静态资源拷贝，不会替你渲染 Jekyll 语法；
> 直接推 Jekyll 源码到 `source/horizon/`，最后只会得到一堆没渲染的 `.md`。因此先 `jekyll build` 成纯静态 HTML。

### 需要你手动完成

1. **把这份 Horizon 推到自己的仓库**（本机已 `git init -b main`，但没有远程/凭据）：

   ```bash
   cd ~/horizon
   git remote add origin git@github.com:<你的用户名>/<仓库名>.git
   git push -u origin main
   ```

2. **创建跨仓库推送用的 PAT**（存为 Secret `PAGES_DEPLOY_TOKEN`）：
   - 目标是 `kfwang90/kfwang90.github.io`，而 `GITHUB_TOKEN` 只能推**当前**仓库 → 必须用 PAT
   - Fine-grained token：Repository access 选 `kfwang90.github.io`，权限 **Contents: Read and write**
   - 或 classic token：勾选 `repo` 作用域
   - 生成地址：GitHub → Settings → Developer settings → Personal access tokens

3. **在 Horizon 仓库配 Secrets / Variables**（Settings → Secrets and variables → Actions）：
   - Secret `PAGES_DEPLOY_TOKEN` = 上面的 PAT
   - Secret `OPENROUTER_API_KEY` = 你的 OpenRouter key（https://openrouter.ai/keys）
   - Variable（可选）`PAGES_REPO` = `kfwang90/kfwang90.github.io`（不填则按 `<owner>/<owner>.github.io` 推断）
   - Variable（可选）`HORIZON_AI_MODEL` = 模型 id（默认 `google/gemini-2.5-flash-lite`）
   - 可选：Secret `HORIZON_WEBHOOK_URL`、`LWN_KEY`

4. **不需要动 Pages 设置**：保持 Source = **GitHub Actions** 即可。

5. **【必须】在 `kfwang90.github.io/_config.yml` 让 Hexo 跳过渲染该目录**：

   ```yaml
   skip_render:
     - 'horizon/**'
   ```

   > 这是实测得出的必需项：Hexo 会把 `source/` 下的 `.html` 当**页面**用主题模板渲染
   > （内容被套进 post 布局、`{{ }}` 被 Nunjucks 吃掉）。加 `skip_render` 后才原样拷贝。
   > 本机 `~/kfwang90.github.io/_config.yml` 已改好（仅此一处改动），记得提交并推送：

   ```bash
   cd ~/kfwang90.github.io
   git add _config.yml
   git commit -m "chore: skip_render horizon/** for Horizon daily digest"
   git push
   ```

6. **首次运行**：Horizon 仓库 → Actions → Daily Horizon Summary → Run workflow。
   Horizon 推送到 Hexo 仓库后会触发其 `static.yml`，等它构建完成后访问 `https://kfwang90.github.io/horizon/`。

### 说明

- 工作流会先执行 `cp data/config.github.json data/config.json`，因此 **CI 用的是 `data/config.github.json`**。
  该文件的模型写作 `${HORIZON_AI_MODEL}`，由工作流的 `env` 注入（默认回退 `google/gemini-2.5-flash-lite`）。
- 构建时会把 `docs/_config.yml` 的 `baseurl` 改成 `/horizon`、`url` 改成 `https://<owner>.github.io`，
  使站内链接指向子目录（仅运行时修改，不改仓库里的文件）。
- 推送用 `dest_dir: source/horizon` + `keep_files: true`，**不会动** Hexo 仓库里的其它内容。
- 用 PAT 推送才会**触发**目标仓库的 Actions（用 `GITHUB_TOKEN` 推送不会触发工作流）。
- `data/config.json`、`.env` 已在 `.gitignore` 中，不会被提交。


## 4. 相关文件清单

- `data/config.json`：本地运行配置（AI 使用 OpenRouter）
- `data/config.github.json`：CI 运行配置
- `.env`：本地密钥与模型（`OPENROUTER_API_KEY=...`、`HORIZON_AI_MODEL=...`）
- `.github/workflows/daily-summary.yml`：定时自动化工作流
