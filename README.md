# 微信-codex/workbuddy聊天智能助理

通过微信与电脑 Codex 或 WorkBuddy 自然对话，并把公众号文章、重点知识与待办整理到 Obsidian。

**核心功能：1、普通聊天自由讨论和执行任务。2、发送公众号文章链接到聊天窗口，整理文章要点，用户可在聊天语音描述重点备注及需要补充查询的信息，机器人助理整理完成后按用户要求进行分类，存储到电脑知识库。** 

## 下载安装

[直接下载 Skill 1.0.0 安装包](https://github.com/owen119110119-beep/wechat-local-assistant/releases/download/v1.0.0/wechat-local-assistant-1.0.0.zip) · [版本页](https://github.com/owen119110119-beep/wechat-local-assistant/releases/tag/v1.0.0) · [SHA256 校验和](https://github.com/owen119110119-beep/wechat-local-assistant/releases/download/v1.0.0/SHA256SUMS.txt)

仓库内也保留[安装包备份](dist/wechat-local-assistant-1.0.0.zip)。

安装包根目录直接包含 SKILL.md。请下载上述包导入 WorkBuddy；

- **Codex**：把 Skill 文件夹放入用户的 `.codex/skills/wechat-local-assistant`，在对话里调用 `$wechat-local-assistant`，由助理按 [部署说明](references/codex-install.md) 检测本机、配置专用目录及知识库、安装项目依赖、扫码接入。已经运行的助理不需重复部署或扫码。
- **WorkBuddy**：在“技能 → 添加技能 → 上传技能”导入安装包，然后在助理会话中启用此 Skill，并告知知识库路径。采用 WorkBuddy 官方原生微信连接及其自身工具，详见 [WorkBuddy 安装](references/workbuddy.md)。导入 Skill 不等于微信已经绑定或服务已经启动。
- **Obsidian**：先检测已有安装与知识库，保留用户笔记和插件；确实未安装才安装。详见 [Obsidian 安装及分类](references/obsidian.md)。

Codex 网关部署脚本面向 Windows。本项目要求 Node.js >=22.13、Python >=3.10、PowerShell 7，并使用已登录的本机 Codex。WorkBuddy 使用自身模型和运行环境，能力与 Codex 不会自动完全相同。

## 文章与日常交流

1. 收到公众号链接：读完整正文，反馈简洁核心要点，主动追问重点备注或补充需求。
2. 收到用户需求：实际分析、调研或完成相应任务，再整理要点；分类建议独立反馈，询问如何分类及是否列入待办。

任一环节都可继续提出溯源、对比、改写、文件操作或其他问题，不会因为尚未选分类而阻塞。文字与已转写语音等效。

纯聊天不自动保存。一篇文章只入普通或重点之一，另建相关待办可以独立执行。待办中的研究应写已查得的具体结果，而不是把调研责任转交用户。

预置的内容结构，可以根据自己的习惯进行修改。
|类型|保存结构|
|---|---|
|普通信息|我的随手转发/普通信息库/类别/YYYY-MM-DD/标题-YYYYMMDD.md|
|重点关注|我的随手转发/重点关注/用途/标题-YYYYMMDD.md|
|主题待办|我的突发奇想/待办事项/标题-YYYYMMDD.md|

类别随内容和用途动态建议。重点按用途分类，日期仅判断时效；普通按类别后再日期留档。修改已有主题保留手写内容、先备份、避免重复并读回核验。

完整规则唯一来源：[最终交互规则](references/interaction.md)。

## 微信入口与运行条件

电脑必须开机联网，且codex保持运行。Codex 可以配置用户登录后隐藏自启，不是未登录即运行的系统服务。

【注意】微信只允许一个AI助理通道，如果你已配置助理通道，则再次绑定该助理，会替换你的原有助理。同理，在开通本助理后，如果再绑定其他助理，本助理会被替换。
