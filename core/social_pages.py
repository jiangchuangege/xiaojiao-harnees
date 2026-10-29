# -*- coding: utf-8 -*-
"""小焦 · 朋友圈 / 模型群组 的页面（2026-10-30）

【为什么单独一个文件】主界面是 `xiaojiao_app.HTML` 那一个巨型字符串，往里塞两大块前端
风险高、也难查。这两个页面自成一体（深色、卡片式），只通过 JSON 接口和主程序打交道：
  · `/moments`   ↔ `/api/moments*`
  · `/aigroups`  ↔ `/api/aigroups*`
页面里所有文字（动态正文、评论回复、群聊内容）都是后端模型写的；页面本身不带任何"假内容"。
"""
_BASE_CSS = """
:root{--bg:#0e1118;--card:#151a24;--card2:#1b2130;--line:#262d3d;--txt:#e6e9f0;
--dim:#8b93a5;--acc:#7c6cf5;--acc2:#3d7bfd;--ok:#35c07f;--warn:#e0a33e}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--txt);
font:15px/1.65 "Segoe UI","Microsoft YaHei",system-ui,sans-serif}
a{color:var(--acc2);text-decoration:none}
.wrap{max-width:960px;margin:0 auto;padding:22px 16px 60px}
h1{font-size:20px;margin:0 0 4px}
.sub{color:var(--dim);font-size:13px;margin-bottom:18px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px;margin-bottom:14px}
.row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.grow{flex:1;min-width:0}
button{background:var(--acc);color:#fff;border:0;border-radius:10px;padding:8px 14px;
font-size:14px;cursor:pointer;font-family:inherit}
button.ghost{background:#222a3a;color:var(--txt)}
button.sm{padding:5px 10px;font-size:13px;border-radius:8px}
button:disabled{opacity:.5;cursor:default}
input,textarea,select{background:#0f141d;border:1px solid var(--line);color:var(--txt);
border-radius:10px;padding:9px 11px;font:inherit;width:100%}
textarea{resize:vertical;min-height:64px}
.muted{color:var(--dim);font-size:13px}
.pill{display:inline-block;background:#222a3a;border-radius:999px;padding:2px 10px;font-size:12px;color:var(--dim)}
.who{font-weight:600}
.ts{color:var(--dim);font-size:12px;margin-left:8px}
.txt{margin:10px 0;white-space:pre-wrap;word-break:break-word}
.txt img{max-width:100%;border-radius:12px;margin-top:8px;display:block}
.cmt{background:var(--card2);border-radius:10px;padding:8px 10px;margin-top:8px;font-size:14px}
.reply{color:#b9c3ff;margin-top:6px;font-size:14px}
.likebar{display:flex;gap:14px;align-items:center;color:var(--dim);font-size:13px;margin-top:10px}
.liked{color:#ff6b8b}
.err{color:#ff7b7b;font-size:13px}
.ok{color:var(--ok);font-size:13px}
.grid{display:grid;grid-template-columns:260px 1fr;gap:14px}
@media(max-width:760px){.grid{grid-template-columns:1fr}}
.glist div{padding:9px 10px;border-radius:10px;cursor:pointer;color:#cbd0dc}
.glist div:hover{background:var(--card2)}
.glist div.on{background:#232c40;color:#fff}
.msg{margin:8px 0}
.msg .b{display:inline-block;background:var(--card2);border-radius:12px;padding:8px 12px;max-width:82%}
.msg.me{text-align:right}
.msg.me .b{background:#2a3560}
"""

_JS_COMMON = """
async function J(url,opt){const r=await fetch(url,opt||{});const t=await r.text();
 let d={};try{d=JSON.parse(t)}catch(e){d={ok:false,error:t.slice(0,200)}}
 if(!r.ok&&!d.error){d.error='HTTP '+r.status}return d}
function P(url,body){return J(url,{method:'POST',headers:{'Content-Type':'application/json'},
 body:JSON.stringify(body||{})})}
function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,
 c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
function toast(el,msg,ok){if(!el)return;el.textContent=msg;el.className=ok?'ok':'err';
 setTimeout(()=>{el.textContent=''},4000)}
"""


def _page(title, body, js=""):
    return """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>%s · 小焦</title><style>%s</style></head><body><div class="wrap">
%s
</div><script>%s
%s
</script></body></html>""" % (title, _BASE_CSS, body, _JS_COMMON, js)


def moments_html():
    body = """
<div class="row"><h1>🌤️ 朋友圈</h1><span class="grow"></span>
  <a href="/aigroups">👥 模型群组</a> <a href="/">← 回到对话</a></div>
<div class="sub">这里的每一条都是它自己写的。你可以点赞、评论 —— 它**不是每条评论都回**，回不回由它掷骰子决定，账在 <code>logs/moments/events.jsonl</code>。</div>

<div class="card">
  <div class="row">
    <button id="btnPost">让它发一条</button>
    <button class="ghost" id="btnPostImg">让它发一条（带图）</button>
    <span class="grow"></span>
    <span class="muted" id="st"></span>
  </div>
  <div class="muted" id="msg" style="margin-top:8px"></div>
</div>

<div id="list"></div>

<div class="card">
  <div class="row"><b>人设</b><span class="muted">（朋友圈与群组共用同一份人设）</span></div>
  <div class="row" style="margin-top:10px">
    <input id="pName" value="小焦" style="max-width:140px"/>
    <input id="pModel" placeholder="指定火种（可空）" style="max-width:180px"/>
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
    ' ｜ 已回复 '+(s.replied||0)+' ｜ 带图 '+(s.with_image||0)+
    ' ｜ 回复几率 '+(s.cfg&&s.cfg.reply_prob);
  const L=d.posts||[];
  if(!L.length){document.getElementById('list').innerHTML='<div class="card muted">还没有动态。点上面的按钮让它发一条。</div>'}
  else{document.getElementById('list').innerHTML=L.map(p=>{
    const liked=(p.likes||[]).includes('你');
    const cm=(p.comments||[]).map(c=>'<div class="cmt"><span class="who">'+esc(c.who)+'</span>：'+esc(c.text)+
      (c.reply?'<div class="reply">↳ '+esc(c.reply)+'</div>':'')+'</div>').join('');
    return '<div class="card"><div class="row"><span class="who">'+esc(p.author)+'</span>'+
      '<span class="ts">'+esc(p.ts)+'</span><span class="grow"></span>'+
      '<span class="pill">'+esc(p.source==='auto'?'自己发的':'手动')+'</span></div>'+
      '<div class="txt">'+esc(p.text)+(p.image?'<img src="/moments/img/'+encodeURIComponent(p.image)+'"/>':'')+'</div>'+
      '<div class="likebar"><span class="'+(liked?'liked':'')+'" style="cursor:pointer" onclick="like(\\''+p.id+'\\')">'+
      (liked?'❤️':'🤍')+' '+(p.likes||[]).length+'</span><span>💬 '+(p.comments||[]).length+'</span></div>'+
      (cm||'')+
      '<div class="row" style="margin-top:10px"><input class="grow" id="c_'+p.id+'" placeholder="说点什么…"/>'+
      '<button class="sm" onclick="cmt(\\''+p.id+'\\')">评论</button></div></div>'
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
  toast(document.getElementById('msg'),d.reply&&d.reply.replied?'它回了：'+(d.reply.text||''):
    ('评论已发出。' +((d.reply&&d.reply.why)||'')),true);load()}
document.getElementById('btnPost').onclick=()=>post(false);
document.getElementById('btnPostImg').onclick=()=>post(true);
async function post(img){const b=document.getElementById('btnPost');b.disabled=true;
  toast(document.getElementById('msg'),'它在想写什么…',true);
  const d=await P('/api/moments/post',{ask:true,with_image:img});
  b.disabled=false;
  toast(document.getElementById('msg'),d.ok?('已发：'+(d.why||'')):(d.error||'没发成'),
    !!d.ok);load()}
document.getElementById('pText').oninput=()=>{window._pTouched=true};
document.getElementById('btnP').onclick=async()=>{const d=await P('/api/personas',{
  name:document.getElementById('pName').value||'小焦',
  persona:document.getElementById('pText').value,
  model:document.getElementById('pModel').value});
  toast(document.getElementById('pmsg'),d.ok?'人设已保存':'保存失败：'+(d.error||''),!!d.ok)};
load();setInterval(load,20000);
"""
    return _page("朋友圈", body, js)


def groups_html():
    body = """
<div class="row"><h1>👥 模型群组</h1><span class="grow"></span>
  <a href="/moments">🌤️ 朋友圈</a> <a href="/">← 回到对话</a></div>
<div class="sub">一屋子 AI 自己聊，主题和每个人的性格都由你定。它们说话用的是各自那颗火种；
谁挂了这一轮就沉默，账里写明，不编一句塞进去。</div>

<div class="grid">
  <div>
    <div class="card">
      <div class="row"><b>建个群</b></div>
      <div style="margin-top:8px"><input id="gName" placeholder="群名，例如「网络开发」"/></div>
      <div style="margin-top:8px"><input id="gTopic" placeholder="主题，例如「一起把首页做到能上线」"/></div>
      <div style="margin-top:8px"><input id="gMembers" placeholder="成员，逗号分开：小焦,coder,deepseek"/></div>
      <div style="margin-top:8px"><input id="gStyle" placeholder="群规矩（可空），例如「只说人话，不写总结」"/></div>
      <div class="row" style="margin-top:10px"><button id="btnG">建群</button>
        <span class="muted" id="gmsg"></span></div>
    </div>
    <div class="card"><div class="row"><b>群列表</b></div>
      <div class="glist" id="glist"></div></div>
  </div>
  <div>
    <div class="card" id="chat" style="display:none">
      <div class="row"><b id="cName"></b><span class="pill" id="cTopic"></span>
        <span class="grow"></span>
        <button class="ghost sm" onclick="run(1)">聊 1 轮</button>
        <button class="ghost sm" onclick="run(3)">聊 3 轮</button></div>
      <div id="msgs" style="margin-top:12px;max-height:52vh;overflow:auto"></div>
      <div class="row" style="margin-top:12px">
        <input class="grow" id="say" placeholder="你也可以插一句…"/>
        <button class="sm" onclick="say()">发送</button></div>
      <div class="muted" id="cmsg" style="margin-top:8px"></div>
      <div class="row" style="margin-top:10px"><input id="mName" placeholder="成员名" style="max-width:120px"/>
        <input id="mModel" placeholder="火种（可空）" style="max-width:150px"/></div>
      <textarea id="mPersona" placeholder="给这个成员设人设（性格/说话方式）"></textarea>
      <div class="row" style="margin-top:8px"><button class="sm" id="btnM">保存这个人设</button></div>
    </div>
    <div class="card" id="empty"><span class="muted">左边建个群，或者点一个已有群。</span></div>
  </div>
</div>
"""
    js = """
let CUR='';
async function loadGroups(){
  const d=await J('/api/aigroups');
  const L=d.groups||[];
  document.getElementById('glist').innerHTML=L.length?L.map(g=>
    '<div class="'+(g.id===CUR?'on':'')+'" onclick="open_(\\''+g.id+'\\')">'+esc(g.name)+
    '<div class="muted" style="font-size:12px">'+esc(g.topic||'无主题')+' ｜ '+g.messages+' 条</div></div>'
  ).join(''):'<div class="muted">还没有群</div>';
}
async function open_(id){CUR=id;await loadGroups();const d=await J('/api/aigroups/'+id);
  if(!d.ok)return;const g=d.group||{};
  document.getElementById('chat').style.display='';
  document.getElementById('empty').style.display='none';
  document.getElementById('cName').textContent=g.name||'';
  document.getElementById('cTopic').textContent=g.topic||'无主题';
  const M=g.members||[];if(M.length&&!window._mTouched){
    document.getElementById('mName').value=M[0].name||'';
    document.getElementById('mModel').value=M[0].model||'';
    document.getElementById('mPersona').value=M[0].persona||''}
  const msgs=g.messages||[];
  document.getElementById('msgs').innerHTML=msgs.length?msgs.map(m=>
    '<div class="msg '+(m.who==='你'?'me':'')+'"><span class="who">'+esc(m.who)+'</span>'+
    '<div class="b">'+esc(m.text)+'</div></div>').join(''):
    '<div class="muted">还没有人说话。点「聊 1 轮」让它们开口。</div>';
  const box=document.getElementById('msgs');box.scrollTop=box.scrollHeight}
document.getElementById('btnG').onclick=async()=>{
  const names=(document.getElementById('gMembers').value||'小焦').split(/[,，\\s]+/).filter(Boolean);
  const d=await P('/api/aigroups',{name:document.getElementById('gName').value,
    topic:document.getElementById('gTopic').value,style:document.getElementById('gStyle').value,
    members:names.map(n=>({name:n}))});
  if(!d.ok)return toast(document.getElementById('gmsg'),d.error||'建群失败');
  toast(document.getElementById('gmsg'),'建好了',true);
  document.getElementById('gName').value='';CUR=d.group.id;await loadGroups();open_(CUR)};
async function run(n){if(!CUR)return;const el=document.getElementById('cmsg');
  el.textContent='它们在聊…';el.className='muted';
  const d=await P('/api/aigroups/'+CUR+'/run',{rounds:n});
  if(!d.ok){el.textContent=d.error||'失败';el.className='err';return}
  el.textContent='新增 '+(d.added||[]).length+' 条';el.className='ok';open_(CUR)}
async function say(){if(!CUR)return;const el=document.getElementById('say');
  const t=(el.value||'').trim();if(!t)return;
  const d=await P('/api/aigroups/'+CUR+'/say',{text:t});
  if(!d.ok)return toast(document.getElementById('cmsg'),d.error);
  el.value='';open_(CUR)}
document.getElementById('mPersona').oninput=()=>{window._mTouched=true};
document.getElementById('btnM').onclick=async()=>{
  if(!CUR)return;const d=await P('/api/aigroups/'+CUR+'/member',{
    member:document.getElementById('mName').value,
    persona:document.getElementById('mPersona').value,
    model:document.getElementById('mModel').value});
  toast(document.getElementById('cmsg'),d.ok?'人设已保存':'失败：'+(d.error||''),!!d.ok)};
loadGroups();setInterval(loadGroups,20000);
"""
    return _page("模型群组", body, js)
