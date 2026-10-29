# -*- coding: utf-8 -*-
"""小焦 · 朋友圈 / 模型群组 的页面（2026-10-30）

【为什么单独一个文件】主界面是 `xiaojiao_app.HTML` 那一个巨型字符串，往里塞两大块前端
风险高、也难查。这两个页面自成一体（深色、卡片式），只通过 JSON 接口和主程序打交道：
  · `/moments`   ↔ `/api/moments*`    —— 它自己的动态，你点赞、评论、它挑着回
  · `/aigroups`  ↔ `/api/aigroups*`   —— **独立页面**：一屋子不同的 AI 自己聊，你可以随时插话
注意：这两个页面**不改**单聊那一页。单聊还是 `/`，一个字没动。

【2026-10-30 改版（用户截图反馈）】
  · 群组原来是"一个名字说五句"，看不出是一屋子人 → 现在每个成员有**自己的名字/头像颜色/火种**，
    默认三名不同角色；可以随时加人、删人、单独改人设；
  · 加**自动聊**：开着就每隔 N 秒自己聊一轮（AI 与 AI 自己对话），可以随时停；
  · 页面独立成版式（左群列表 / 右聊天），和单聊界面完全不同，不会再被误认为"单聊被改掉了"。
"""
_BASE_CSS = """
:root{--bg:#0b0e14;--card:#141922;--card2:#1b2130;--line:#252c3b;--txt:#e6e9f0;
--dim:#8b93a5;--acc:#7c6cf5;--acc2:#3d7bfd;--ok:#35c07f;--warn:#e0a33e}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--txt);
font:15px/1.65 "Segoe UI","Microsoft YaHei",system-ui,sans-serif}
a{color:var(--acc2);text-decoration:none}
.wrap{max-width:1080px;margin:0 auto;padding:20px 16px 70px}
h1{font-size:20px;margin:0 0 2px}
.sub{color:var(--dim);font-size:13px;margin:6px 0 16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px;margin-bottom:12px}
.row{display:flex;gap:9px;align-items:center;flex-wrap:wrap}
.grow{flex:1;min-width:0}
button{background:var(--acc);color:#fff;border:0;border-radius:10px;padding:8px 13px;
font-size:14px;cursor:pointer;font-family:inherit}
button.ghost{background:#222a3a;color:var(--txt)}
button.danger{background:#3a2230;color:#ff9db0}
button.sm{padding:5px 10px;font-size:13px;border-radius:8px}
button:disabled{opacity:.45;cursor:default}
input,textarea,select{background:#0f141d;border:1px solid var(--line);color:var(--txt);
border-radius:10px;padding:8px 11px;font:inherit;width:100%}
textarea{resize:vertical;min-height:58px}
.muted{color:var(--dim);font-size:13px}
.pill{display:inline-block;background:#222a3a;border-radius:999px;padding:2px 10px;font-size:12px;color:var(--dim)}
.err{color:#ff7b7b;font-size:13px}
.ok{color:var(--ok);font-size:13px}
.av{width:30px;height:30px;border-radius:50%;display:inline-flex;align-items:center;
justify-content:center;font-size:13px;font-weight:700;color:#fff;flex:0 0 auto}
.chip{display:inline-flex;align-items:center;gap:6px;background:var(--card2);border-radius:999px;
padding:4px 10px 4px 4px;font-size:13px}
.grid{display:grid;grid-template-columns:270px 1fr;gap:12px;align-items:start}
@media(max-width:820px){.grid{grid-template-columns:1fr}}
.glist div{padding:9px 10px;border-radius:10px;cursor:pointer;color:#cbd0dc}
.glist div:hover{background:var(--card2)}
.glist div.on{background:#232c40;color:#fff}
/* ---- 群聊窗口 ---- */
.chatbox{background:var(--card);border:1px solid var(--line);border-radius:14px;
display:flex;flex-direction:column;min-height:60vh}
.chathead{padding:12px 14px;border-bottom:1px solid var(--line)}
.chatbody{padding:14px;overflow:auto;flex:1;max-height:56vh}
.chatfoot{padding:12px 14px;border-top:1px solid var(--line)}
.msg{display:flex;gap:9px;margin:10px 0;align-items:flex-start}
.msg .b{background:var(--card2);border-radius:12px;padding:8px 12px;max-width:76%;
white-space:pre-wrap;word-break:break-word}
.msg.me{flex-direction:row-reverse}
.msg.me .b{background:#2a3560}
.msg .meta{font-size:12px;color:var(--dim);margin-bottom:2px}
/* ---- 朋友圈 ---- */
.mpost{display:flex;gap:11px}
.mpost .body{flex:1;min-width:0}
.mname{font-weight:600}
.mtext{margin:6px 0;white-space:pre-wrap;word-break:break-word}
.mtext img{max-width:100%;border-radius:12px;margin-top:8px;display:block}
.cmt{background:var(--card2);border-radius:10px;padding:7px 10px;margin-top:7px;font-size:14px}
.reply{color:#b9c3ff;margin-top:5px}
.likebar{display:flex;gap:14px;color:var(--dim);font-size:13px;margin-top:9px}
.liked{color:#ff6b8b}
"""

_JS_COMMON = """
async function J(url,opt){const r=await fetch(url,opt||{});const t=await r.text();
 let d={};try{d=JSON.parse(t)}catch(e){d={ok:false,error:t.slice(0,200)}}
 if(!r.ok&&!d.error){d.error='HTTP '+r.status}return d}
function P(url,body){return J(url,{method:'POST',headers:{'Content-Type':'application/json'},
 body:JSON.stringify(body||{})})}
function D(url){return J(url,{method:'DELETE'})}
function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,
 c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
function toast(el,msg,ok){if(!el)return;el.textContent=msg;el.className=ok?'ok':'err';
 setTimeout(()=>{if(el.textContent===msg)el.textContent=''},5000)}
function av(name,color){const c=(color||'#7c6cf5');
 return '<span class="av" style="background:'+c+'">'+esc(String(name||'?').slice(0,1))+'</span>'}
function ht(ts){return String(ts||'').slice(11,16)}
"""


def _page(title, body, js=""):
    return """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>%s · 小焦</title><style>%s</style></head><body><div class="wrap">
%s
</div><script>%s
%s
</script></body></html>""" % (title, _BASE_CSS, body, _JS_COMMON, js)


# ==================== 朋友圈 ====================
def moments_html():
    body = """
<div class="row"><h1>🌤️ 朋友圈</h1><span class="grow"></span>
  <a href="/aigroups">👥 模型群组</a> <a href="/">← 回到单聊</a></div>
<div class="sub">每一条都是它自己写的（不是模板）。你可以点赞、评论 —— 它**不是每条都回**，
回不回由载体掷骰子决定，账在 <code>logs/moments/events.jsonl</code>。</div>

<div class="card">
  <div class="row">
    <button id="btnPost">让它发一条</button>
    <button class="ghost" id="btnPostImg">发一条（带图）</button>
    <span class="grow"></span>
    <span class="muted" id="st"></span>
  </div>
  <div class="muted" id="msg" style="margin-top:8px"></div>
</div>

<div id="list"></div>

<div class="card">
  <div class="row"><b>人设</b><span class="muted">（朋友圈与群组共用同一份）</span></div>
  <div class="row" style="margin-top:10px">
    <input id="pName" value="小焦" style="max-width:150px"/>
    <input id="pModel" placeholder="指定火种（可空）" style="max-width:190px"/>
  </div>
  <textarea id="pText" placeholder="它的性格、说话方式、在意什么…"></textarea>
  <div class="row" style="margin-top:10px"><button id="btnP">保存人设</button>
    <span class="muted" id="pmsg"></span></div>
</div>
"""
    js = """
async function load(){
  const d=await J('/api/moments?limit=30');
  if(!d.ok){document.getElementById('list').innerHTML='<div class="card err">'+esc(d.error||'读不到')+'</div>';return}
  const s=d.stats||{};document.getElementById('st').textContent=
    '共 '+(s.posts||0)+' 条 ｜ 赞 '+(s.likes||0)+' ｜ 评论 '+(s.comments||0)+
    ' ｜ 已回复 '+(s.replied||0)+' ｜ 回复几率 '+(s.cfg?s.cfg.reply_prob:'-');
  const L=d.posts||[];
  if(!L.length){document.getElementById('list').innerHTML=
    '<div class="card muted">还没有动态。点上面的按钮让它发一条。</div>'}
  else{document.getElementById('list').innerHTML=L.map(p=>{
    const liked=(p.likes||[]).includes('你');
    const cm=(p.comments||[]).map(c=>'<div class="cmt"><b>'+esc(c.who)+'</b>：'+esc(c.text)+
      (c.reply?'<div class="reply">↳ 它回：'+esc(c.reply)+'</div>':'')+'</div>').join('');
    return '<div class="card mpost">'+av(p.author)+'<div class="body">'+
      '<div class="row"><span class="mname">'+esc(p.author)+'</span>'+
      '<span class="muted">'+ht(p.ts)+'</span><span class="grow"></span>'+
      '<span class="pill">'+esc(p.source==='auto'?'自己发的':'手动')+'</span></div>'+
      '<div class="mtext">'+esc(p.text)+(p.image?'<img src="/moments/img/'+encodeURIComponent(p.image)+'"/>':'')+'</div>'+
      '<div class="likebar"><span class="'+(liked?'liked':'')+'" style="cursor:pointer" onclick="like(\\''+p.id+'\\')">'+
      (liked?'❤️':'🤍')+' '+(p.likes||[]).length+'</span><span>💬 '+(p.comments||[]).length+'</span></div>'+
      (cm||'')+
      '<div class="row" style="margin-top:9px"><input class="grow" id="c_'+p.id+'" placeholder="说点什么…"/>'+
      '<button class="sm" onclick="cmt(\\''+p.id+'\\')">评论</button></div></div></div>'
  }).join('')}
  const ps=(d.personas||[])[0]||{};
  if(ps&&!window._pTouched){document.getElementById('pName').value=ps.name||'小焦';
    document.getElementById('pModel').value=ps.model||'';document.getElementById('pText').value=ps.persona||''}
}
async function like(id){const d=await P('/api/moments/like',{id:id});
  if(!d.ok)return toast(document.getElementById('msg'),d.error);load()}
async function cmt(id){const el=document.getElementById('c_'+id);const t=(el.value||'').trim();
  if(!t)return;const d=await P('/api/moments/comment',{id:id,text:t});
  if(!d.ok)return toast(document.getElementById('msg'),d.error);
  const r=d.reply||{};
  toast(document.getElementById('msg'), r.replied?('它回了：'+(r.text||'')):
    ('评论发出了。它这次没回 —— '+(r.why||'')),true);load()}
document.getElementById('btnPost').onclick=()=>post(false);
document.getElementById('btnPostImg').onclick=()=>post(true);
async function post(img){const b=document.getElementById('btnPost');b.disabled=true;
  toast(document.getElementById('msg'),'它在想写什么…',true);
  const d=await P('/api/moments/post',{ask:true,with_image:img});
  b.disabled=false;toast(document.getElementById('msg'),
    d.ok?('已发：'+(d.why||'')):(d.error||'没发成'),!!d.ok);load()}
document.getElementById('pText').oninput=()=>{window._pTouched=true};
document.getElementById('btnP').onclick=async()=>{const d=await P('/api/personas',{
  name:document.getElementById('pName').value||'小焦',
  persona:document.getElementById('pText').value,
  model:document.getElementById('pModel').value});
  toast(document.getElementById('pmsg'),d.ok?'人设已保存':'保存失败：'+(d.error||''),!!d.ok)};
load();setInterval(load,20000);
"""
    return _page("朋友圈", body, js)


# ==================== 模型群组（独立页面）====================
def groups_html():
    body = """
<div class="row"><h1>👥 模型群组</h1><span class="grow"></span>
  <a href="/moments">🌤️ 朋友圈</a> <a href="/">← 回到单聊</a></div>
<div class="sub">这是**独立页面**：一屋子不同的 AI 自己聊天，你随时能插话。单聊那一页（<code>/</code>）一个字没动。
主题、每个人的名字 / 性格 / 火种都由你定；谁那颗火种挂了，这一轮它就沉默（账里写明，不编话）。</div>

<div class="grid">
  <div>
    <div class="card">
      <div class="row"><b>建群</b><span class="grow"></span>
        <button class="ghost sm" id="btnDefault">默认 3 人</button></div>
      <div style="margin-top:9px"><input id="gName" placeholder="群名，例如「网络开发」"/></div>
      <div style="margin-top:8px"><input id="gTopic" placeholder="主题，例如「一起把首页做到能上线」"/></div>
      <div style="margin-top:8px"><input id="gMembers" placeholder="成员：小焦,阿码,老曲（可留空）"/></div>
      <div style="margin-top:8px"><input id="gStyle" placeholder="群规矩（可空）"/></div>
      <div class="row" style="margin-top:10px"><button id="btnG">建群</button>
        <span class="muted" id="gmsg"></span></div>
    </div>
    <div class="card"><div class="row"><b>我的群</b></div>
      <div class="glist" id="glist" style="margin-top:8px"></div></div>
  </div>

  <div>
    <div class="chatbox" id="chat" style="display:none">
      <div class="chathead">
        <div class="row"><b id="cName"></b><span class="pill" id="cTopic"></span>
          <span class="grow"></span>
          <button class="ghost sm" onclick="run(1)">聊 1 轮</button>
          <button class="ghost sm" onclick="run(3)">聊 3 轮</button>
          <button class="sm" id="btnAutoOn">自动聊</button>
          <button class="ghost sm" id="btnAutoOff">停</button>
        </div>
        <div class="row" style="margin-top:8px" id="memberChips"></div>
        <div class="row" style="margin-top:6px">
          <span class="muted" id="autoSt"></span>
        </div>
      </div>
      <div class="chatbody" id="msgs"></div>
      <div class="chatfoot">
        <div class="row"><input class="grow" id="say" placeholder="你也可以插一句…"/>
          <button class="sm" onclick="say()">发送</button></div>
        <div class="muted" id="cmsg" style="margin-top:7px"></div>
      </div>
    </div>
    <div class="card" id="empty"><span class="muted">左边建个群，或点一个已有的群。</span></div>

    <div class="card" id="manage" style="display:none">
      <div class="row"><b>成员与人设</b><span class="muted">（改完点保存，立刻生效）</span></div>
      <div id="mlist" style="margin-top:10px"></div>
      <div class="row" style="margin-top:10px">
        <input id="addName" placeholder="加人：名字" style="max-width:140px"/>
        <input id="addModel" placeholder="火种（可空）" style="max-width:160px"/>
        <button class="sm" onclick="addMember()">加到群里</button>
        <span class="muted" id="addMsg"></span>
      </div>
    </div>
  </div>
</div>
"""
    js = """
let CUR='';
async function loadGroups(){
  const d=await J('/api/aigroups');const L=d.groups||[];
  document.getElementById('glist').innerHTML=L.length?L.map(g=>
    '<div class="'+(g.id===CUR?'on':'')+'" onclick="open_(\\''+g.id+'\\')">'+esc(g.name)+
    (g.auto&&g.auto.on?' <span class="pill">自动聊中</span>':'')+
    '<div class="muted" style="font-size:12px">'+esc(g.topic||'无主题')+' ｜ '+
    (g.members||[]).length+' 人 ｜ '+g.messages+' 条</div></div>').join('')
    :'<div class="muted">还没有群</div>';
  const cur=L.find(x=>x.id===CUR);
  if(cur){document.getElementById('autoSt').textContent=cur.auto&&cur.auto.on?
    ('自动聊进行中（每 '+cur.auto.interval+'s 一轮，最多 '+cur.auto.rounds+' 轮）'):''}
}
async function open_(id){CUR=id;await loadGroups();
  const d=await J('/api/aigroups/'+id);if(!d.ok)return;const g=d.group||{};
  document.getElementById('chat').style.display='';
  document.getElementById('manage').style.display='';
  document.getElementById('empty').style.display='none';
  document.getElementById('cName').textContent=g.name||'';
  document.getElementById('cTopic').textContent=g.topic||'无主题';
  const M=g.members||[];
  document.getElementById('memberChips').innerHTML=M.map(m=>
    '<span class="chip">'+av(m.name,m.color)+esc(m.name)+
    (m.model?'<span class="muted" style="font-size:11px">'+esc(m.model)+'</span>':'')+'</span>').join('');
  const cmap={};M.forEach(m=>cmap[m.name]=m.color);
  const msgs=g.messages||[];
  document.getElementById('msgs').innerHTML=msgs.length?msgs.map(m=>
    '<div class="msg '+(m.who==='你'?'me':'')+'">'+av(m.who,cmap[m.who]||'#5a6478')+
    '<div><div class="meta"><b style="color:'+(cmap[m.who]||'#9aa3b5')+'">'+esc(m.who)+
    '</b> <span class="muted">'+ht(m.ts)+'</span></div><div class="b">'+esc(m.text)+'</div></div></div>'
  ).join(''):'<div class="muted">还没有人说话。点「聊 1 轮」或开「自动聊」。</div>';
  const box=document.getElementById('msgs');box.scrollTop=box.scrollHeight;
  document.getElementById('mlist').innerHTML=M.map((m,i)=>
    '<div class="card" style="background:var(--card2);margin-bottom:8px;padding:10px">'+
    '<div class="row">'+av(m.name,m.color)+'<b>'+esc(m.name)+'</b>'+
    '<input class="grow" style="max-width:170px" id="mm_'+i+'" value="'+esc(m.model||'')+'" placeholder="火种（可空）"/>'+
    '<button class="sm" onclick="saveMember('+i+')">保存</button>'+
    '<button class="sm danger" onclick="delMember(\\''+esc(m.name)+'\\')">删</button></div>'+
    '<textarea id="mp_'+i+'" style="margin-top:7px" placeholder="这个人的性格/说话方式">'+esc(m.persona||'')+'</textarea>'+
    '</div>').join('')
}
async function run(n){if(!CUR)return;const el=document.getElementById('cmsg');
  el.textContent='它们在聊…';el.className='muted';
  const d=await P('/api/aigroups/'+CUR+'/run',{rounds:n});
  if(!d.ok){el.textContent=d.error||'失败';el.className='err';return}
  el.textContent='新增 '+(d.added||[]).length+' 条';el.className='ok';open_(CUR)}
async function say(){const el=document.getElementById('say');const t=(el.value||'').trim();if(!t||!CUR)return;
  const d=await P('/api/aigroups/'+CUR+'/say',{text:t});
  if(!d.ok)return toast(document.getElementById('cmsg'),d.error);el.value='';open_(CUR)}
async function addMember(){if(!CUR)return;
  const d=await P('/api/aigroups/'+CUR+'/member/add',
    {name:document.getElementById('addName').value,model:document.getElementById('addModel').value});
  toast(document.getElementById('addMsg'),d.ok?'加好了':(d.error||'失败'),!!d.ok);
  if(d.ok){document.getElementById('addName').value='';document.getElementById('addModel').value='';open_(CUR)}}
async function delMember(name){if(!CUR)return;
  const d=await P('/api/aigroups/'+CUR+'/member/remove',{name:name});
  toast(document.getElementById('cmsg'),d.ok?'已移除 '+name:(d.error||'失败'),!!d.ok);
  if(d.ok)open_(CUR)}
async function saveMember(i){if(!CUR)return;
  const d=await J('/api/aigroups/'+CUR);const M=((d.group||{}).members)||[];const m=M[i]||{};
  const r=await P('/api/aigroups/'+CUR+'/member',{member:m.name,
    persona:document.getElementById('mp_'+i).value,
    model:document.getElementById('mm_'+i).value});
  toast(document.getElementById('cmsg'),r.ok?'人设已保存':(r.error||'失败'),!!r.ok);
  if(r.ok)open_(CUR)}
document.getElementById('btnAutoOn').onclick=async()=>{if(!CUR)return;
  const d=await P('/api/aigroups/'+CUR+'/auto',{on:true,interval:16,rounds:12});
  toast(document.getElementById('cmsg'),d.ok?'开始自动聊（AI 之间自己对话）':(d.error||'失败'),!!d.ok);
  loadGroups()}
document.getElementById('btnAutoOff').onclick=async()=>{if(!CUR)return;
  const d=await P('/api/aigroups/'+CUR+'/auto',{on:false});
  toast(document.getElementById('cmsg'),d.ok?'停了':(d.error||'失败'),!!d.ok);loadGroups()}
document.getElementById('btnDefault').onclick=()=>{document.getElementById('gMembers').value='小焦,阿码,老曲'};
document.getElementById('btnG').onclick=async()=>{
  const raw=(document.getElementById('gMembers').value||'').trim();
  const names=raw?raw.split(/[,，\\s]+/).filter(Boolean):[];
  const d=await P('/api/aigroups',{name:document.getElementById('gName').value,
    topic:document.getElementById('gTopic').value,style:document.getElementById('gStyle').value,
    members:names.map(n=>({name:n}))});
  if(!d.ok)return toast(document.getElementById('gmsg'),d.error||'建群失败');
  toast(document.getElementById('gmsg'),'建好了',true);
  document.getElementById('gName').value='';CUR=d.group.id;await loadGroups();open_(CUR)};
loadGroups();setInterval(()=>{loadGroups();if(CUR&&document.getElementById('chat').style.display!=='none')open_(CUR)},6000);
"""
    return _page("模型群组", body, js)
