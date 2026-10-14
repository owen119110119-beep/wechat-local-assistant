---
name: wechat-local-assistant
description: 部署或维护本机微信智能助理，连接 Codex 或 WorkBuddy、配置 Obsidian，并按用户最终约定整理公众号文章及自然语言补充需求。适用于微信助理安装、接入、知识分类、入库和排障。
---

# 微信本机智能助理

微信只是入口。普通对话由宿主真实 Agent 理解和执行，不用固定意图、关键词、字段模板或确认口令。仅文章整理遵守用户约定的两步反馈；流程不能阻挡用户在任何环节提出的新任务。

部署先确定宿主、安装目录和知识库目录，读现有状态及规则。已运行的助理不重新绑定或创建第二个消费者。默认 Windows 本机，其他系统不得直接运行 Windows 自启脚本。

- **Codex**：读 [Codex 部署](references/codex-install.md)，使用捆绑真实 Agent 网关；已有成功运行版本可只安装此 Skill，不重部署服务。
- **WorkBuddy**：读 [WorkBuddy 安装与第二窗口](references/workbuddy.md)，使用官方原生微信助理及 WorkBuddy 自身工具；不启动 Codex 网关冒充 WorkBuddy。
- **共同交互与分类**：读 [最终交互规则](references/interaction.md)。这是唯一行为规则源，部署脚本注入同一文件。
- **Obsidian**：读 [安装及知识库](references/obsidian.md)，复用已有库，绝不重置用户笔记或插件。
- **故障/迁移**：读 [运行与验证](references/operations.md)，根据具体层级修复，不循环回复含糊的重试提示。

包包含运行时代码及独立公众号读取器，无账号、凭据、对话、笔记、模型或安装好的依赖。导入 Skill 不等于登录模型、扫码微信或启动服务成功。首次手机扫码及宿主账号登录必须由用户完成；真实收到回复且保存读回后才能报告该链路接通。
