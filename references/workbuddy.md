# WorkBuddy 安装

WorkBuddy 使用自身模型、工具和原生微信连接，不需要安装 Codex 网关。

先按[安装检查](installation-check.md)核对实际助理会话的本机执行、读写、图片、检索与附件工具。缺少工具时提前告知并引导开启；不能把Codex能力推定为WorkBuddy能力。

已有本Skill的部署目录，先用新版`scripts/upgrade.py --target 原安装目录 --check-only`核对，确认可升级后去掉`--check-only`更新共享规则与读取脚本；保留已有知识库路径及自定义内容，不重新扫码。本文路线用于原生微信对话、文章/素材和知识整理；独立本机群数据库入口见[Windows Codex群聊整理](group-chat.md)。

1. 安装并登录 WorkBuddy，在“技能 → 添加技能 → 上传技能”导入安装包，启用本 Skill。
2. 告知助理知识库路径，使用以下命令创建本机规则和配置，示例路径换成实际路径：

```powershell
python scripts/install.py --host workbuddy --target "D:\微信WorkBuddy助理" --vault "D:\个人知识库"
```

3. 在 WorkBuddy“助理 → 设置 → 微信助理集成 → 配置”中扫码接入。已有 ClawBot 绑定时，重新绑定会替换原助理。
4. 在微信助理实际使用的会话中启用本 Skill，读取部署目录的 AGENTS.md 并记住知识库路径；使用宿主支持的规则或记忆功能保持后续会话生效。
5. 手机发送普通消息确认连接，再发送公众号链接开始整理。电脑与 WorkBuddy 保持运行。

公众号正文由 Skill 的 `scripts/read_wechat_article.py URL --output-dir 本机临时目录 --quiet` 读取，随后读生成的正文和元数据。检索、讨论和文件操作使用 WorkBuddy 自身工具。总结与分类建议分别表达；文字和已转写语音同等处理。依据实际读取、检索和保存结果回复。

统一入口补齐共享读取依赖；需要本机转写时追加`--with-media`，不安装Codex网关。按[素材读取](content-reading.md)调用共享读取脚本；图像编辑和附件回传须使用WorkBuddy实际工具并完成手机往返核对。

升级后需要图片总结PDF时，在原部署目录运行`python scripts/setup-content.py`补齐依赖；已有模型、账号和笔记保留。连续图片、个性化处理及成果回微信按[图片整理](image-workflow.md)执行，使用WorkBuddy实际开放的编辑和附件工具。
