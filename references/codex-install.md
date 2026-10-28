# Codex 部署（Windows）

先检测已有安装。新用户部署到专用空目录；升级使用新版Skill中的`scripts/upgrade.py`，不重复绑定或注册自启。

已有本Skill部署的助理，先等任务结束并停止服务，再执行`python 新版Skill目录/scripts/upgrade.py --target 原安装目录 --check-only`核对，去掉`--check-only`执行升级。脚本备份被替换文件，保留配置、绑定、消息、依赖和知识库；发现自定义代码或旧规则改动则保留并交给助理合并，不能覆盖。同版升级后，按下面步骤配置Codex启动接入，再用`scripts/start.ps1`启动，无需重新扫码。旧版启用过Windows登录自启的，先用PowerShell 7运行`scripts/autostart-task.ps1 -Mode Disable`移除旧任务，不影响绑定和笔记。

先检测并登录官方 Codex，准备 Node.js >=22.13、Python >=3.10、PowerShell 7。优先使用已有或 Codex 捆绑运行时，缺少时安装官方版本；不覆盖已有环境。Codex 需支持本机 App Server，连接错误按运行说明排查。

从旧安装升级后，恢复服务前在原部署目录运行`python scripts/setup-content.py`，补齐图片总结PDF所需的项目依赖；已有微信绑定、知识库和本机转写模型保留，不需要重新下载模型或扫码。

用本机 Python 在 Skill 根目录执行，示例路径换成用户选择的实际路径：

```powershell
python scripts/deploy.py --host codex --target "D:\微信智能助理" --vault "D:\个人知识库"
node scripts/install-dependencies.mjs --root "D:\微信智能助理"
```

安装目标使用新的专用空目录，知识库可复用已有目录。脚本保留原有笔记与配置，权限仅覆盖助理目录和知识库。依赖安装使用部署配置中检测到的运行时；公众号读取器无需额外依赖。已有语音转写直接使用。

随后进入部署目录执行 `python scripts/setup-content.py --with-media`，配置小红书、PDF、Office、图片和音视频读取；具体使用见[素材读取](content-reading.md)。

进入部署目录，使用 `config/local.json` 中的 nodePath 运行 `scripts/pair-weixin.mjs`，打开生成的本机二维码页面，由用户手机扫码。凭据仅保存至本机 `.runtime/credentials/`，不复用其他助理凭据；验证码由用户在本机终端输入。已绑定 ClawBot 时先告知重新绑定会替换原入口。

扫码完成后用 PowerShell 7 执行：

```powershell
pwsh -NoProfile -File scripts/start.ps1
node scripts/configure-codex-startup.mjs --shell "PowerShell7的实际完整路径"
```

启动接入使用Codex原生本机扩展。重新打开Codex并加载或恢复聊天时，会隐藏启动微信助理；不绑定Windows登录、不做周期检查，也不会因反复进入聊天而重复启动。服务通过一次性隐藏交接启动，关闭或归档单条桌面聊天不会终止服务；不改变现有代理环境。配置修改在下次Codex加载时生效，当前可用start立即启动。主动stop后保持停止，需要恢复时运行start。电脑须开机联网，Codex需运行。核对实际连接并请用户从手机发一条普通消息；保存时核查实际文件。启动失败查具体错误，不反复扫码。

需要整理指定群时，再按[群聊整理](group-chat.md)启用；新安装默认关闭，不扫描聊天记录或预设任何群。
