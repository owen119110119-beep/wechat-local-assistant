---
name: wechat-local-assistant
description: 安装、升级或维护微信本机智能助理，连接 Codex 或 WorkBuddy 与 Obsidian，整理公众号、素材和指定群消息，保留自然对话、知识分类及待办。
---

# 微信本机智能助理

普通聊天自然讨论并执行任务；公众号按两步整理，用户在任何环节提出的新需求都要响应。

先确定宿主、专用安装目录和知识库路径，检测已有安装。已有助理升级保留配置、绑定与笔记，不重新部署或扫码。

- Codex：按 [部署说明](references/codex-install.md) 安装本机网关，适用于 Windows。
- WorkBuddy：按 [安装说明](references/workbuddy.md) 使用原生微信连接及自身工具。
- 两个宿主均执行 [交互与分类规则](references/interaction.md)，部署脚本使用同一规则文件。
- Obsidian：按 [知识库配置](references/obsidian.md) 复用已有安装和笔记。
- 指定群消息（Windows Codex）：按 [群聊整理](references/group-chat.md) 按需启用本机读取；只处理用户指定的群，不自动读取所有聊天。
- 小红书、网页、PDF、Office、图片和音视频：按 [素材读取](references/content-reading.md) 获取正文及本机证据，再按用户需求整理。
- 排障：按 [运行说明](references/operations.md) 查实际状态并处理具体错误。

首次宿主登录和微信扫码由用户完成。凭据仅留本机，不输出到聊天或日志；收到手机回复、实际写入并读回文件后，才报告对应操作成功。
