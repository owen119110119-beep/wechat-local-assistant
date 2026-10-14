# 微信本机智能助理

通过微信与本机 Codex 或 WorkBuddy 自然对话，并把公众号文章、重点知识与待办整理到 Obsidian。

**普通聊天自由讨论和执行任务。文章整理保留两步流程，用户的补充需求不限格式。** 本项目采用最终版真实 Agent 交互，不包含早期固定意图路由和机械确认流程。

## 下载安装

[直接下载 Skill 1.0.0 安装包](https://github.com/owen119110119-beep/wechat-local-assistant/releases/download/v1.0.0/wechat-local-assistant-1.0.0.zip) · [版本页](https://github.com/owen119110119-beep/wechat-local-assistant/releases/tag/v1.0.0) · [SHA256 校验和](https://github.com/owen119110119-beep/wechat-local-assistant/releases/download/v1.0.0/SHA256SUMS.txt)

仓库内也保留[安装包备份](dist/wechat-local-assistant-1.0.0.zip)。

安装包根目录直接包含 SKILL.md。请下载上述包导入 WorkBuddy；GitHub 自带“Download ZIP”包含整个仓库及外层目录，不能视作同一个导入包。

- **Codex**：把 Skill 文件夹放入用户的 `.codex/skills/wechat-local-assistant`，在对话里调用 `$wechat-local-assistant`，由助理按 [部署说明](references/codex-install.md) 检测本机、配置专用目录及知识库、安装项目依赖、扫码接入。已经运行的助理不需重复部署或扫码。
- **WorkBuddy**：在“技能 → 添加技能 → 上传技能”导入安装包，然后在助理会话中启用此 Skill，并告知知识库路径。采用 WorkBuddy 官方原生微信连接及其自身工具，详见 [WorkBuddy 安装](references/workbuddy.md)。导入 Skill 不等于微信已经绑定或服务已经启动。
- **Obsidian**：先检测已有安装与知识库，保留用户笔记和插件；确实未安装才安装。详见 [Obsidian 安装及分类](references/obsidian.md)。

Codex 网关部署脚本面向 Windows。本项目要求 Node.js >=22.13、Python >=3.10、PowerShell 7，并使用已登录的本机 Codex。WorkBuddy 使用自身模型和运行环境，能力与 Codex 不会自动完全相同。

## 文章与日常交流

1. 收到公众号链接：读完整正文，反馈简洁核心要点，主动追问重点备注或补充需求。
2. 收到用户需求：实际分析、调研或完成相应任务，再整理要点；分类建议独立反馈，询问如何分类及是否列入待办。

任一环节都可继续提出溯源、对比、改写、文件操作或其他问题，不会因为尚未选分类而阻塞。文字与已转写语音等效。用户已明确分类或待办指令，就直接执行，不再索取二次确认口令；内部编号不展示给用户。

纯聊天不自动保存。一篇文章只入普通或重点之一，另建相关待办可以独立执行。待办中的研究应写已查得的具体结果，而不是把调研责任转交用户。

|类型|保存结构|
|---|---|
|普通信息|我的随手转发/普通信息库/类别/YYYY-MM-DD/标题-YYYYMMDD.md|
|重点关注|我的随手转发/重点关注/用途/标题-YYYYMMDD.md|
|主题待办|我的突发奇想/待办事项/标题-YYYYMMDD.md|

类别随内容和用途动态建议。重点按用途分类，日期仅判断时效；普通按类别后再日期留档。修改已有主题保留手写内容、先备份、避免重复并读回核验。

完整规则唯一来源：[最终交互规则](references/interaction.md)。

## 微信入口与运行条件

电脑必须开机联网，对应宿主/服务保持运行。Codex 可以配置用户登录后隐藏自启，不是未登录即运行的系统服务。每个微信绑定只允许一个轮询消费者，不能共享运行中的 token。

再次绑定其他平台 ClawBot 可能顶替已有助理，不能把重新扫码当作必然新增第二个微信窗口。保留现有 Codex 时，可考虑 WorkBuddy 官方微信客服号作为另一个入口；实际并存仍需手机验收。见 [官方渠道与验证边界](references/workbuddy.md)。

## 验证与数据

1.0.0 已通过标准 Skill 格式检查、20项 Agent/会话/移植测试、隔离部署与已有笔记保护检查，以及本机真实 Codex 初始化和临时回复。WorkBuddy 实际导入、手机新绑定及双入口未完成实机验收，不把自动测试等同于手机往返成功。

仓库和安装包不包含用户账号凭据、微信消息、会话数据库、个人知识库、本机诊断资料、转写模型或已安装依赖。部署后的 `.runtime`、`.venv`、`node_modules` 和 `config/local.json` 仅留本机，禁止提交。

公众号读取只接受公开 mp.weixin.qq.com HTTPS 正文，不用 cookie 或第三方阅读服务；遇验证页如实说明，不凭标题编造。平台沙箱与审批保留，额外权限的动作不能假称执行成功。

GitHub 在国内不同网络下连通性不一致；不能保证无 VPN 稳定下载。如主站/单文件下载失败，可通过可访问网络获取安装包，再在本地导入。

[运行与排障](references/operations.md)
