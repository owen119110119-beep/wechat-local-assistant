# 素材读取

首次使用[统一安装检查](installation-check.md)补齐依赖并验证。在已有部署运行`python scripts/setup-assistant.py`可检查并修复到该目录`.venv`；确需本机音频转写才加`--with-media`。保留已有环境和转写模型；浏览器优先使用可运行的Chrome，缺少或启动失败时使用项目专用Chromium。视频工具随项目安装，不依赖其他Skill。安装包不携带账号、模型或用户素材。

Codex网关自动处理微信收到的小红书分享链接、网页链接及图片/文件/音视频附件。已转写的语音直接作为用户需求使用。WorkBuddy使用自身工具接收附件，然后调用部署目录中的同一读取脚本。

```powershell
.venv\Scripts\python.exe -X utf8 scripts/content_reader.py url --input "用户提供的HTTPS链接" --output-dir ".runtime\content\本次素材" --model-dir ".runtime\models\base"
.venv\Scripts\python.exe -X utf8 scripts/content_reader.py file --input "本机附件完整路径" --output-dir ".runtime\content\本次素材" --model-dir ".runtime\models\base"
```

读取生成的 `content.json` 和 `content.md`；图片看 `imageEvidence` 的本机图片与OCR，视频看 `evidencePath` 中的时间转写、画面及OCR。正文和配图都要覆盖，账号与网址对照原图；视频封面、简介不代表看过视频。`partial` 表示有未读部分，`ready_for_review` 表示证据已准备，仍需分析。失败时结合具体reason处理，保留已读取部分。

小红书支持 `xhslink.cn`、`xhslink.com` 与完整笔记链接。遇登录要求时，用部署目录 `.venv\Scripts\python.exe scripts/browser_provider.py auth --provider xiaohongshu` 打开专用浏览器，请用户完成一次登录；后续复用本机登录，不让用户发Cookie或密码，不处理验证码绕过。

PDF支持正文和扫描页OCR；Office支持DOCX、PPTX、XLSX；图片OCR与音视频证据使用本机处理。链接及文档整理沿用文章两步规则；连续课件图片和明确图片任务按[图片整理](image-workflow.md)收齐后整合或直接响应，生成物不自动入库。收到新素材时以新素材为当前对象；普通聊天继续自然回应。
