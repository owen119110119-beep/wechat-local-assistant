---
name: wechat-local-assistant
description: 部署或维护微信本机智能助理，连接 Codex 或 WorkBuddy、配置 Obsidian，支持自然对话、公众号整理、知识分类和待办保存。
---

# 微信本机智能助理

普通聊天自然讨论并执行任务；公众号按两步整理，用户在任何环节提出的新需求都要响应。

安装时先确定宿主、专用安装目录和知识库路径，检测已有安装。已运行的助理不重复部署或扫码。

- Codex：按 [部署说明](references/codex-install.md) 安装本机网关，适用于 Windows。
- WorkBuddy：按 [安装说明](references/workbuddy.md) 使用原生微信连接及自身工具。
- 两个宿主均执行 [交互与分类规则](references/interaction.md)，部署脚本使用同一规则文件。
- Obsidian：按 [知识库配置](references/obsidian.md) 复用已有安装和笔记。
- 排障：按 [运行说明](references/operations.md) 查实际状态并处理具体错误。

首次宿主登录和微信扫码由用户完成。凭据仅留本机，不输出到聊天或日志；收到手机回复、实际写入并读回文件后，才报告对应操作成功。
