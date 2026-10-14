// Internal capture/thread identifiers never cross the mobile output boundary.
export function mobileText(text) {
  return String(text).replace(/-?[AIV][0-9a-f]{10}\b/gi,'')
    .replace(/\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b/gi,'')
    .replace(/(?:重试|取消)\s+编号/g,x=>x.split(/\s/)[0]);
}
export const captureTitle=c=>c.title||c.draft?.title||c.article?.title||c.idea?.title||(c.kind==='video'?'对标视频':'正文尚未读取的文章');
export const capturePhase=c=>({reading:'读取中',analyzing:'提炼中',drafting:'整理中',writing:'保存中',await_focus:'等待关注点',await_opinion:'等待你的意见',await_confirmation:'等待分类或待办意见',await_video_save:'链接等待保存指令',failed:'尚未完成，可重试',archived:'已入库',cancelled:'已取消'})[c.status]||'待整理';
