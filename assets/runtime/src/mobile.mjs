// Shared instruction for every model entry, not a filter or a reply template.
export const LINK_WORKFLOW='所有用户发来的新链接都按同一整理流程处理，包括公众号、视频号、其他视频、小红书、网页和文件链接；不能按平台或历史习惯跳过追问。首次先实际读取和分析、反馈简洁核心要点，主动追问希望重点备注或补充什么，此轮不入知识库。链接附带需求或类别也先记住，仍保留重点追问；收到补充回应后结合需求实际分析或调研、重新整理要点，分类建议单独反馈，询问尚未明确的分类及是否记待办。已有明确意见不二次索要确认，按当前真实选择执行。旧的对标视频自动留档、只存链接持续开关和历史默认分类均已撤销，不是本次保存授权；不要恢复。无法读取就如实说明具体可读范围并继续追问所需重点或替代资料，不能凭封面编要点，更不能用保存网址代替整理。用户后续可自由提出任何任务，不被分类流程卡住；只有当前明确保存意见才可入库。';
export const USER_COMMUNICATION=`用户沟通规则，同时适用于进度气泡、最终答复、分类建议、保存结果和笔记正文：
普通任务只交流用户关心的实际进展、成果、必要澄清及影响完成的具体限制。内部工具说明、算法、字段、状态值、后台配置、权限机制、修复历史和开发验证只用于操作，不主动介绍、逐字复述或作为能力公告。用户重复任务也不等于询问技术变化。能直接做就做，无需每轮先宣布能力；必要进度简短自然，不能在实际读取前声称读完。
${LINK_WORKFLOW}
群名需澄清时只说实际名称及必要差异，不介绍匹配机制；时间/重点只问缺项。分类前可完成整理，群摘要类型与文章普通/重点分开。
分类建议讲内容用途及建议位置，不复述目录生成、授权或状态流转。保存时实际写入并核对，只反馈保存了什么和用户需要的相对分类位置，不主动播报幂等、原子写入、回执、哈希、备份步骤或读回校验。详细本机路径、临时文件、内部编号和英文字段不塞进普通回复或笔记。原文链接、来源日期和用户所需技术内容照常保留。
失败如实说明哪个步骤没完成、已经完成的部分及可行下一步；工具错误转换为用户能理解的原因，不直接贴错误码或程序日志，不把失败说成没有资料，不凭推测断言未同步。未核对实际文件时不能保证完全没写入或宣称已保存。取消只停止所指工作，已保存内容不能假称删除；继续或重试先核对已有结果，避免重复操作。
用户主动问技术、配置、故障原因或原理时正常解释相关细节，不隐瞒真实限制。技术资料/源文里的术语与用户要研究的技术内容不应删掉。以上是自然表达要求，不是固定话术、词表过滤或对自由任务及工具的限制。`;

export function userFailure(error){
 const detail=[error?.message,error?.rpcDetail].filter(Boolean).join(' ');
 if(/ARTICLE_VERIFICATION_REQUIRED/u.test(detail))return '这篇文章打开后出现微信验证页面，暂时没读到正文。可以把正文粘贴过来，我再继续整理。';
 if(/ARTICLE_BODY_UNAVAILABLE/u.test(detail))return '这篇文章暂时没读到正文，无法可靠整理。可以把正文粘贴过来；已收到的链接和要求保留。';
 if(/ARTICLE_NETWORK_OR_TIMEOUT/u.test(detail))return '这篇文章的页面未能打开，可能是请求失败或等待超时；链接和要求保留，可以稍后继续或提供正文。';
 if(/ARTICLE_TOO_LONG/u.test(detail))return '这篇文章较长，暂未完成读取。可以指定重点部分分段整理；链接和要求保留。';
 if(/VOICE_TOO_LONG|VOICE_TOO_LARGE/u.test(detail))return '这段语音太长，暂未能处理。请分成较短的几段发送，也可以补充文字。';
 if(/VOICE_/u.test(detail)||error?.userContext==='voice')return '这段语音未能转成可用文字，尚未按其中要求执行。请重新发一段语音或补充文字。';
 if(/VAULT_(?:CONTENT_CHANGED|CONFLICT|EXISTS)|ASSISTANT_NOTE_CHANGED/u.test(detail))return '这篇笔记已有内容或刚被修改，我没有直接覆盖。需要先核对现有内容，再合并你的补充。';
 if(/VAULT_|ASSISTANT_WRITE/u.test(detail))return '笔记尚未保存完成。继续前需要先核对是否已有部分内容，避免重复或覆盖原笔记。';
 if(/CHATDB_NEW_SHARD/u.test(detail))return '电脑微信新增了一部分聊天记录，助理暂时还不能读取这一部分，当前不能保证整理完整；需要先恢复读取后继续。';
 if(/CHATDB_GROUP_SELECTION_CANCELLED/u.test(detail))return '已停止整理这个群，没有继续读取。';
 if(/CHATDB_READER_BUSY/u.test(detail))return '另一项聊天记录整理正在读取，暂时没能开始这一步；等它读完后可以继续。';
 if(/CHATDB_/u.test(detail))return '这次没能读到指定的聊天记录，整理尚未完成；不能据此判断群里没有消息，需要先核对目标和读取情况。';
 if(/CODEX_RUNTIME_/u.test(detail))return '电脑上的 Codex 更新后缺少运行文件，暂时无法继续操作；需求保留，需要先恢复完整安装。';
 if(/CODEX_RPC_TIMEOUT/u.test(detail))return /^(?:initialize|account\/read|thread\/(?:start|resume|fork))$/u.test(error?.rpcMethod||'')?'本机 Codex 接续对话等待超时，本次任务尚未开始执行；要求已保留，恢复连接后可以继续。':'与 Codex 通信等待超时，尚未确认本次执行结果；要求已保留，继续前需要先核对执行状态。';
 if(/interrupted|CANCELLED/iu.test(detail))return '本次任务已停止，已有内容保留。';
 if(/quota|rate.limit|usage.limit|exhausted/iu.test(detail))return 'Codex 当前使用额度或请求频率受限，这次工作没有完成；额度恢复后可以继续。';
 if(/login|log(?:ged)?[ _-]?in|token|authenticat|unauthoriz/iu.test(detail))return '本机 Codex 登录状态异常，暂时无法继续；恢复登录后可以接着处理。';
 if(/TIMEOUT|timed? ?out/iu.test(detail))return '本次处理超时，尚未完成。已有资料保留，可以继续或缩小处理范围；继续前会先核对已完成的部分。';
 if(/active writer/iu.test(detail))return '当前对话暂时无法接续，需求和已有结果保留，需要先恢复连接再继续。';
 if(/network|connect|socket|fetch/iu.test(detail))return '本机与 Codex 的网络连接失败，工作尚未完成；已有消息保留，连接恢复后可以继续。';
 return '本次回复未完成，已有消息保留。继续前需要先核对已完成的部分，避免重复操作。';
}

// Internal capture/thread identifiers never cross the mobile output boundary.
export function mobileText(text) {
  return String(text).replace(/-?[AIV][0-9a-f]{10}\b/gi,'')
    .replace(/\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b/gi,'')
    .replace(/(?:重试|取消)\s+编号/g,x=>x.split(/\s/)[0]);
}
export const captureTitle=c=>c.title||c.draft?.title||c.article?.title||c.idea?.title||(c.kind==='video'?'对标视频':'正文尚未读取的文章');
export const capturePhase=c=>({reading:'读取中',analyzing:'提炼中',drafting:'整理中',writing:'保存中',await_focus:'等待关注点',await_opinion:'等待你的意见',await_confirmation:'等待分类或待办意见',await_video_save:'链接等待保存指令',failed:'尚未完成，可重试',archived:'已入库',cancelled:'已取消'})[c.status]||'待整理';
