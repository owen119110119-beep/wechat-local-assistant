# WorkBuddy 安装与独立微信入口

这是同一个标准 SKILL.md 包，可从 WorkBuddy 设置/技能 → 添加技能 → 上传技能 导入本地 ZIP，并保持启用。官方确认本地技能包导入、SKILL.md 和 .agents 来源兼容；包根为 SKILL.md，不嵌套第二层目录。格式检查已完成不等于特定 WorkBuddy 版本实际导入通过。

WorkBuddy 运行模式：它自身 Agent + 自身微信连接 + 本 Skill 交互规则/独立公众号读取器 + 本机 Obsidian。不会使用 Codex App Server，也不需要登录 Codex。仅通用 Python 部署/读取脚本跨宿主；Codex 专用网关和自启脚本不在此模式运行。

1. 安装登录官方 WorkBuddy（微信接入文档要求 >=4.6.4）、微信 >=8.0.70，账号一致或已关联。
2. 导入 ZIP。在 WorkBuddy 对话明确说“启用 wechat-local-assistant，使用最终交互规则，知识库路径是……”。Skill 不是全局系统提示，不能假设导入后规则已经进入所有会话。
3. 执行 `python scripts/deploy.py --host workbuddy --target "D:\微信WorkBuddy助理" --vault "D:\个人知识库"`，生成本机规则与 profile，不复制 Codex 网关。
4. 助理 → 齿轮 → 微信助理集成 → 配置 → 手机扫码。打开它实际使用的助理专属目录；读取部署目录的 AGENTS.md，向此唯一助理会话说明“以此文件作为后续微信交互规则并使用上述知识库”，按宿主支持的记忆/规则方式保存。不能未经查证宣称宿主会自动加载任意目录 AGENTS.md。
5. 文章读取调用 Skill 的 `scripts/read_wechat_article.py URL --output-dir 本机临时目录 --quiet`；读取生成的 article.json/md，未拿到正文就不能编总结。真实检索和文件写入用 WorkBuddy 已开放工具。摘要与分类建议分两条消息；如果通道只发送最终回复，明确拆分文本，是否多气泡须实机核对。
6. 分别测试纯聊天、链接、语音补充、处理中另问其他问题、明确分类即保存、待办正文与文件读回。测试结束前标记“安装待实机”，不能冒称完全与 Codex 相同。

## 第二个微信聊天窗口：已知与未验证

- 官方确实提供 WorkBuddy 微信助理扫码接入，电脑需要保持运行；另有微信客服号通道。
- 官方 FAQ 写当前一对一绑定；助理功能文档写远程指令集中于一个会话。这不是微信账号只能拥有一个不同产品助理的证明，也不是允许 WorkBuddy 创建任意多个独立助理窗口的保证。
- 阿里云官方微信接入 FAQ 明确描述跨平台机器人互斥：后绑定可顶替先绑定，这是渠道限制。虽然不是腾讯对 WorkBuddy+Codex 组合的直接实测，不应把新 ClawBot 绑定作为安全新增第二窗口方案。
- 已有 Codex ClawBot 时，不再扫码 WorkBuddy 的 ClawBot 通道，不导入旧 token、不解绑 Codex。新机器首次接入才使用上述微信助理扫码步骤。
- 如需保留 Codex 并新增微信内 WorkBuddy 入口，优先按 WorkBuddy 官方“微信客服号”通道独立扫码，不能混为 ClawBot；该组合能否并存仍须实际验收。微信小程序连接电脑也可作为备选，但不是第二个普通聊天窗口。

官方依据（2026-10-14核查）：
- [本地技能导入](https://www.codebuddy.cn/docs/workbuddy/From-Beginner-to-Expert-Guide/Function-Description/Skills-Market)
- [微信助理与一对一绑定 FAQ](https://www.codebuddy.cn/docs/workbuddy/WeixinBot-Guide)
- [远程助理会话/专属目录](https://www.codebuddy.cn/docs/workbuddy/From-Beginner-to-Expert-Guide/Function-Description/Assistant)
- [小程序连接电脑](https://www.codebuddy.cn/docs/workbuddymini/quick-start/Quickstart)
- [微信客服号接入](https://www.codebuddy.cn/docs/workbuddy/Wechat-Guide)
- [阿里云官方跨平台 ClawBot 互斥说明](https://help.aliyun.com/zh/jvs/user-guide/wechat-access)
