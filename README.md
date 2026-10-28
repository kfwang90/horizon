<div align="center">

<h1>🌅 Horizon</h1>

<p><strong>你只需享受新闻，剩下交给 Horizon。</strong></p>

<a href="https://github.com/Thysrael/Horizon/actions/workflows/deploy-docs.yml/badge">
  <img src="https://img.shields.io/badge/Daily-Horizon-blue?style=for-the-badge&logo=date-fns&logoColor=white" alt="Daily" />
</a>
<a href="LICENSE">
  <img src="https://img.shields.io/badge/license-MIT-green.svg?style=for-the-badge&logo=opensourceinitiative&logoColor=white" alt="License" />
</a>
<a href="https://www.horizon1123.top/">
  <img src="https://img.shields.io/badge/Website-Horizon-263238?style=for-the-badge&logo=homepage&logoColor=white" alt="Website" />
</a>

📡 构建你专属的 AI 新闻雷达，生成中英双语日报。 | Your own AI-powered news radar.

[📖 在线演示](https://thysrael.github.io/Horizon/) · [📋 配置指南](https://thysrael.github.io/Horizon/configuration) · [💬 QQ 群](#交流群) · [贡献指南](CONTRIBUTING.md)

---

🎨 **原作者：** [Thysrael](https://github.com/Thysrael)

欢迎贡献和改进！

</div>

## 功能特性

- **📡 把关注汇到一处** — 从 RSS、Hacker News、Reddit、Telegram、X、GitHub 和金融新闻等来源收集内容。
- **🎯 值不值得读，你定标准** — 用 Profile 定义评分规则，分别设置筛选门槛，合并同一 Profile 下的重复报道。
- **🧩 新闻看背景，长文看方法** — 自定义摘要、背景、方案、启示等内容区块，修改 Markdown 提示词和 JSON 配置即可。
- **💬 多看一层，再下判断** — 按需搜索背景、提炼社区讨论，读到标题之外的信息。
- **⚖️ 留下刚好够读的量** — 限制日报总条数和各类内容的份额，让热门话题给其他兴趣留点位置。
- **📬 在你习惯的地方读** — 生成中英双语日报，保存为 Markdown、发布到 Pages，或通过邮件和 Webhook 送达。

## 工作原理

**Profile 定义处理规则，运行配置掌握阅读偏好。** 每条内容路由到一个 Profile，完成分析、筛选和去重后，再为入选内容生成区块，按 Profile 分组渲染成日报。

通过 CLI 运行完整流程，也可通过 [MCP](src/mcp/README.md) 让 AI 助手调用采集、分析和生成等阶段。

## 快速开始

### 1. 安装

```bash
git clone https://github.com/Thysrael/Horizon.git
cd horizon

# 使用 uv 安装（推荐）
uv sync

# 需要测试/开发依赖时
uv sync --extra dev

# 或使用 pip
pip install -e .
```

### 2. 配置

**方式 A：交互式向导（推荐）**

```bash
uv run horizon-wizard
```

向导会询问你的兴趣（如"LLM 推理"、"嵌入式"、"web 安全"），自动推荐并生成 `data/config.json`，还可选让 AI 补充推荐小众源。若你想分享信息源，请前往 [horizon1123.top](https://horizon1123.top/)。CLI 选项见[交互式向导](docs/configuration.md#interactive-wizard)。

**方式 B：手动配置**

```bash
cp .env.example .env          # 添加 API 密钥
cp data/config.example.json data/config.json  # 自定义信息源
```

### 3. 运行

```bash
uv run horizon
```

## 支持的信息源

Horizon 支持以下信息源（各信息源均需配置 `profile`，用于内容筛选与去重）：

| 信息源 | 示例 | Profile |
|------|------|---------|
| RSS 订阅 | [Simon Willison](https://simonwillison.net/atom/everything/) | `tech-news` |
| Hacker News | HN Top Stories | `tech-blog` |
| Reddit | r/technology, r/artificial | `tech-news` |
| Telegram | `@horizon_news` | `tech-news` |
| X（Twitter） | `@simonw` | `social-hot` |
| GitHub | `@karpathy` | `gh-trending` |
| 金融新闻 | OpenBB 支持的股票新闻 | `finance` |

完整信息源配置请参考[配置指南](docs/configuration.md)。

## 获取每日新闻

每日新闻通过以下方式发布：

1. **GitHub Pages**：访问 [Horizon 网站](https://thysrael.github.io/Horizon/) 获取最新日报
2. **邮件推送**：订阅邮件接收每日摘要
3. **Webhook 通知**：通过 Webhook 接口获取新闻数据
4. **微信推送**：关注官方微信获取每日新闻

完整的发布方式配置请参考[配置指南](docs/configuration.md)中的 Webhook 和 Email 章节。

## 文档

- [交互式向导](docs/configuration.md#interactive-wizard) - 自动生成配置
- [配置指南](docs/configuration.md) - 完整配置说明
- [Profile 指南](docs/profiles.md) - 内容处理规则配置
- [MCP 工具](src/mcp/README.md) - AI 助手集成指南
- [架构图](docs/assets/architecture.svg) - 系统架构说明

## 贡献

**[GitHub 仓库](https://github.com/Thysrael/Horizon)** | 欢迎贡献代码、Bug 修复和功能改进。

### 分享信息源

想把有价值的信息源分享给 Horizon 社区？请直接访问 [horizon1123.top](https://horizon1123.top/) 提交。

### 参与开发

1. 提交 Issue - 报告 Bug 或提出功能建议
2. Fork 仓库并创建 Pull Request
3. 参与代码评审和文档更新

## 鸣谢

- **特别感谢 [LINUX.DO](https://linux.do/)** 提供的宣传平台
- **特别感谢 [HelloGitHub](https://hellogithub.com/)** 提供的指导意见
- **特别感谢 [AIGC Link](https://xhslink.com/m/80ngts127cA)** 提供的小红书和微信公众号宣传
- **特别感谢所有贡献者** - Horizon 的发展离不开大家的帮助

[Thysrael](https://github.com/Thysrael) 维护

## 许可证

本项目采用 **MIT 许可证**。请参阅 [LICENSE](LICENSE) 文件获取详细信息。
