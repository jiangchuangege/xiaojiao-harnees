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
function shortName(n){n=String(n||'');return n.length>14?(n.slice(0,12)+'\u2026'):n}
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
<div class="sub">**它自己会发**：后台每隔几分钟读一次它自己的状态（情绪 / 精力 / 没说出口的话 /
刚跟你聊过的事 / 逛世界看到的），够想说了就发一条 —— 每条下面都写着它当时为什么想说。
你也可以催它发（右边那两个按钮），但它照样按自己的状态说，不会被套成模板。</div>

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
      '<span class="pill">'+esc(p.source==='self'?'他自己想发的':(p.source==='auto'?'自己发的':'你催他发的'))+'</span></div>'+
      '<div class="mtext">'+esc(p.text)+(p.image?'<img src="/moments/img/'+encodeURIComponent(p.image)+'"/>':'')+'</div>'+
      (p.why?'<div class="muted" style="font-size:12px">· 他当时的想法：'+esc(p.why)+'</div>':'')+
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
    <div class="card"><div class="row"><b>我的群</b><span class="grow"></span>
      <span class="muted">点群名进房间；✕ 退出</span></div>
      <div class="glist" id="glist" style="margin-top:8px"></div></div>
  </div>
  <div>
    <div class="card"><span class="muted">建好群会自动进它的房间页；也可以直接点左边的群。
      房间里才有「邀请模型」「自动聊」「退出群」。</span></div>
  </div>
</div>
"""
    js = """
function toast(el,m,ok){if(!el)return;el.textContent=m;el.className=ok?'ok':'err';
  setTimeout(()=>{if(el.textContent===m)el.textContent=''},5000)}
async function loadGroups(){
  const d=await J('/api/aigroups');
  const L=d.groups||[];
  const box=document.getElementById('glist');
  if(!L.length){box.innerHTML='<div class="muted">还没有群。左边填个名字建一个。</div>';return}
  box.innerHTML=L.map(function(g){
    const aut=(g.auto&&g.auto.on)?' <span class="pill">自动聊中</span>':'';
    return '<div class="row" style="align-items:flex-start;padding:3px 0">'+
      '<a href="/aigroups/'+g.id+'" style="flex:1;min-width:0;display:block;padding:8px 10px;'+
      'border-radius:10px;background:transparent" class="gopen">'+
      '<b>'+esc(g.name)+'</b>'+aut+
      '<div class="muted" style="font-size:12px">'+esc(g.topic||'无主题')+' ｜ '+
      (g.members||[]).length+' 人 ｜ '+g.messages+' 条</div></a>'+
      '<button class="sm danger" data-gid="'+g.id+'" data-name="'+esc(g.name)+'">✕</button>'+
      '</div>';
  }).join('');
}
async function delGroup(id,name){
  if(!confirm('退出并删除群「'+name+'」？聊天记录会一起没了。'))return;
  const d=await D('/api/aigroups/'+id);
  toast(document.getElementById('gmsg'),d.ok?('已退出「'+name+'」'):(d.error||'失败'),!!d.ok);
  loadGroups();
}
document.getElementById('glist').addEventListener('click',function(ev){
  const b=ev.target.closest('button[data-gid]');
  if(!b)return;
  ev.preventDefault();ev.stopPropagation();
  delGroup(b.dataset.gid,b.dataset.name);
});
document.getElementById('btnDefault').onclick=function(){
  document.getElementById('gMembers').value='小焦,阿码,老曲'};
document.getElementById('btnG').onclick=async function(){
  const nm=(document.getElementById('gName').value||'').trim();
  if(!nm){document.getElementById('gmsg').textContent='先给群起个名字';return}
  const raw=(document.getElementById('gMembers').value||'').trim();
  const names=raw?raw.split(/[,，\\s]+/).filter(Boolean):[];
  const d=await P('/api/aigroups',{name:nm,
    topic:document.getElementById('gTopic').value,
    style:document.getElementById('gStyle').value,
    members:names.map(function(n){return {name:n}})});
  if(!d.ok){toast(document.getElementById('gmsg'),d.error||'建群失败');return}
  location.href='/aigroups/'+d.group.id;
};
loadGroups();setInterval(loadGroups,15000);
"""
    return _page("模型群组", body, js)


# ==================== 单个群的独立房间页 ====================
def group_room_html(gid):
    """群里就该只有群聊：整页一间隔聊窗口 + 三个抽屉（邀请/成员/设置）。"""
    import html as _html

    def _chip(kind, val, existing):
        on = val in (existing or set())
        return ('<button class="sm %s" data-kind="%s" data-val="%s"%s>%s%s</button>'
                % ("ghost" if on else "", kind, _html.escape(str(val), quote=True),
                   " disabled" if on else "", "✓ " if on else "＋ ",
                   _html.escape(str(val))))

    try:
        from core import ai_group as _AG, personas as _PS
        _models = _AG.available_models() or []
        _pnames = [r.get("name") for r in (_PS.list_all() or []) if r.get("name")]
        _g = _AG.get(gid) or {}
    except Exception:      # noqa: silent-ok — 列不出来就给个占位，页面照样能用
        _models, _pnames, _g = [], ["小焦"], {}
    _existing = {m.get("name") for m in (_g.get("members") or [])}
    _model_chips = "".join(_chip("model", x, _existing) for x in (_models or ["（默认火种）"]))
    _persona_chips = "".join(_chip("persona", x, _existing) for x in _pnames)

    body = """
<style>
.room{max-width:900px;margin:0 auto}
.rhead{display:flex;gap:12px;align-items:center;background:var(--card);border:1px solid var(--line);
border-radius:16px;padding:12px 14px;position:sticky;top:8px;z-index:5}
.rhead .gav{width:52px;height:52px;border-radius:14px;background:#2a3140;display:flex;
align-items:center;justify-content:center;font-size:22px;cursor:pointer;overflow:hidden;flex:0 0 auto}
.rhead .gav img{width:100%;height:100%;object-fit:cover}
.rbody{background:var(--card);border:1px solid var(--line);border-radius:16px;margin-top:12px;
display:flex;flex-direction:column;height:calc(100vh - 210px);min-height:340px}
.rmsgs{flex:1;overflow:auto;padding:14px}
.rfoot{border-top:1px solid var(--line);padding:10px 12px}
.drawer{display:none;margin-top:12px;background:var(--card);border:1px solid var(--line);
border-radius:16px;padding:14px}
.drawer.on{display:block}
.mrow{display:flex;align-items:center;gap:9px;padding:8px 0;border-bottom:1px dashed #222a38}
.mrow:last-child{border-bottom:0}
.tag{background:#2a3550;color:#a9b8ff;border-radius:8px;padding:1px 7px;font-size:11px}
.notice{background:#1a2030;border-radius:10px;padding:8px 10px;color:#b9c3d6;font-size:13px;margin-top:8px}
</style>

<div class="room">
  <div class="rhead">
    <div class="gav" id="gav" title="点一下换群头像">__GAV_INIT__</div>
    <div style="flex:1;min-width:0">
      <div class="row"><b id="rName" style="font-size:17px">…</b>
        <span class="pill" id="rAuto">自动聊中</span></div>
      <div class="muted" id="rSub" style="font-size:12px">…</div>
    </div>
    <button class="sm" data-drawer="inv">＋ 邀请</button>
    <button class="ghost sm" data-drawer="mem">成员</button>
    <button class="ghost sm" data-drawer="set">设置</button>
    <a href="/aigroups" class="ghost sm" style="padding:6px 10px;border-radius:10px;background:#222a3a">←</a>
  </div>

  <div class="rbody">
    <div class="rmsgs" id="msgs"></div>
    <div class="rfoot">
      <div class="row"><input class="grow" id="say" placeholder="说点什么…（它自己也会聊，不用你催）"/>
        <button id="btnSay">发送</button></div>
      <div class="row" style="margin-top:7px"><span class="muted" id="cmsg"></span></div>
    </div>
  </div>

  <!-- 邀请抽屉 -->
  <div class="drawer" id="d-inv">
    <div class="row"><b>邀请模型进群</b><span class="muted">（点一下就邀，不用打字）</span>
      <span class="grow"></span><button class="ghost sm" data-close="inv">收起</button></div>
    <div class="muted" style="margin-top:8px">按火种</div>
    <div class="row" id="invModels" style="margin-top:6px">__MODEL_CHIPS__</div>
    <div class="muted" style="margin-top:10px">按人设</div>
    <div class="row" id="invPersonas" style="margin-top:6px">__PERSONA_CHIPS__</div>
    <div class="row" style="margin-top:10px"><button class="ghost sm" id="btnCustom">自定义一个（可选）</button>
      <span class="muted" id="invMsg"></span></div>
    <div id="invCustom" style="display:none;margin-top:8px">
      <div class="row"><input id="invName" placeholder="名字" class="grow"/>
        <input id="invModelCustom" placeholder="火种（可空）" style="max-width:170px"/></div>
      <textarea id="invPersona" placeholder="人设（可空）" style="margin-top:8px"></textarea>
      <div class="row" style="margin-top:8px"><button class="sm" id="btnInvCustom">加进来</button></div>
    </div>
  </div>

  <!-- 成员抽屉 -->
  <div class="drawer" id="d-mem">
    <div class="row"><b>群成员</b><span class="muted">（可设管理员 / 移除）</span>
      <span class="grow"></span><button class="ghost sm" data-close="mem">收起</button></div>
    <div id="mlist" style="margin-top:8px"></div>
  </div>

  <!-- 设置抽屉 -->
  <div class="drawer" id="d-set">
    <div class="row"><b>群设置</b><span class="grow"></span>
      <button class="ghost sm" data-close="set">收起</button></div>
    <div style="margin-top:9px"><input id="setName" placeholder="群名"/></div>
    <div style="margin-top:8px"><input id="setTopic" placeholder="主题"/></div>
    <div style="margin-top:8px"><input id="setNotice" placeholder="群公告（大家都能看到）"/></div>
    <div class="muted" style="margin-top:12px">群节奏（决定它们多爱动手）</div>
    <div class="row" id="paceRow" style="margin-top:6px"></div>
    <div class="muted" style="margin-top:12px">本群共识（每轮自动蒸馏，越聊越多）</div>
    <div id="distillBox" class="notice" style="margin-top:6px"></div>
    <div class="row" style="margin-top:10px"><button class="sm" id="btnSaveSet">保存群资料</button>
      <button class="ghost sm" id="btnAvatar">上传群头像</button>
      <button class="sm danger" id="btnQuit">退出群</button>
      <span class="muted" id="setMsg"></span></div>
    <input type="file" id="avatarFile" accept="image/*" style="display:none"/>
  </div>
</div>
""".replace("__GAV_INIT__", "焦").replace(
        "__MODEL_CHIPS__", _model_chips).replace("__PERSONA_CHIPS__", _persona_chips)

    js = """
const GID='__GID__';let LASTN=0,MODELS=[],NAMES={};
function toast(el,m,ok){if(!el)return;el.textContent=m;el.className=ok?'ok':'err';
  setTimeout(function(){if(el.textContent===m)el.textContent=''},5000)}
function openDrawer(k){
  ['inv','mem','set'].forEach(function(x){
    document.getElementById('d-'+x).classList.toggle('on',x===k)});
  if(k==='set')fillSettings();
}
function closeDrawer(k){document.getElementById('d-'+k).classList.remove('on')}
async function inviteModel(model){
  const d=await P('/api/aigroups/'+GID+'/invite',{model:model});
  toast(document.getElementById('invMsg'),
    d.ok?('已邀请 '+model):((d.failed||[]).join('、')||d.error||'失败'),!!d.ok);
  if(d.ok)load();}
async function invitePersona(name){
  const d=await P('/api/aigroups/'+GID+'/invite',{name:name});
  toast(document.getElementById('invMsg'),
    d.ok?('已邀请 '+name):((d.failed||[]).join('、')||d.error||'失败'),!!d.ok);
  if(d.ok)load();}
async function toggleAdmin(name,on){
  const d=await P('/api/aigroups/'+GID+'/admin',{name:name,on:on});
  toast(document.getElementById('cmsg'),d.ok?((on?'设为管理员：':'取消管理员：')+name):(d.error||'失败'),!!d.ok);
  if(d.ok)load();}
async function togglePerm(name,on){
  const d=await P('/api/aigroups/'+GID+'/perm',{name:name,allow_tools:on});
  toast(document.getElementById('cmsg'),d.ok?((on?'已允许动手：':'已禁止动手：')+name):(d.error||'失败'),!!d.ok);
  if(d.ok)load();}
async function delMember(name){
  const r=await P('/api/aigroups/'+GID+'/member/remove',{name:name});
  toast(document.getElementById('cmsg'),r.ok?'已移出 '+name:(r.error||'失败'),!!r.ok);
  if(r.ok)load();}
async function saveMemberPersona(name,i){
  const r=await P('/api/aigroups/'+GID+'/member',{member:name,
    persona:document.getElementById('mp_'+i).value,
    model:document.getElementById('mm_'+i).value});
  toast(document.getElementById('cmsg'),r.ok?'人设已保存':(r.error||'失败'),!!r.ok);
  if(r.ok)load();}
async function runRounds(n){
  const el=document.getElementById('cmsg');el.textContent='它们在聊…';el.className='muted';
  const d=await P('/api/aigroups/'+GID+'/run',{rounds:n});
  if(!d.ok){el.textContent=d.error||'失败';el.className='err';return}
  el.textContent='新增 '+(d.added||[]).length+' 条';el.className='ok';load();}
async function saySomething(){
  const el=document.getElementById('say');const t=(el.value||'').trim();if(!t)return;
  const d=await P('/api/aigroups/'+GID+'/say',{text:t});
  if(!d.ok){toast(document.getElementById('cmsg'),d.error);return}
  el.value='';load();}
const PACES=[['chat','聊天群（少动手）'],['mixed','混合'],['dev','开发群（多动手）']];
async function setPace(k){
  const d=await P('/api/aigroups/'+GID+'/pace',{pace:k});
  toast(document.getElementById('setMsg'),d.ok?('节奏已切到 '+k):(d.error||'失败'),!!d.ok);
  if(d.ok)load();
}
async function fillSettings(){
  const d0=await J('/api/aigroups/'+GID);const g0=(d0.group||{});
  const cur=g0.pace||'mixed';
  document.getElementById('paceRow').innerHTML=PACES.map(function(x){
    return '<button class="sm '+(x[0]===cur?'':'ghost')+'" data-pace="'+x[0]+'">'+
      (x[0]===cur?'✓ ':'')+x[1]+'</button>'}).join('');
  document.getElementById('paceRow').querySelectorAll('button[data-pace]').forEach(function(b){
    b.onclick=function(){setPace(b.dataset.pace)}});
  const ds=g0.distilled||[];
  document.getElementById('distillBox').innerHTML=ds.length?
    ds.slice(-6).map(function(x){return '· '+esc(x.note||'')}).join('<br>'):
    '（还没有。它们聊几轮就会自己蒸馏出来）';
  const d=await J('/api/aigroups/'+GID);if(!d.ok)return;const g=d.group||{};
  document.getElementById('setName').value=g.name||'';
  document.getElementById('setTopic').value=g.topic||'';
  document.getElementById('setNotice').value=g.notice||'';
}
async function load(){
  const d=await J('/api/aigroups/'+GID);
  if(!d.ok){document.getElementById('msgs').innerHTML='<div class="err">'+esc(d.error||'读不到这个群')+'</div>';return}
  const g=d.group||{};
  const M=g.members||[];const cmap={};NAMES={};
  M.forEach(function(x){cmap[x.name]=x.color;NAMES[x.name]=x});
  document.getElementById('rName').textContent=g.name||'';
  document.getElementById('rSub').textContent=(g.topic||'无主题')+' ｜ '+M.length+' 人'+
    (g.notice?' ｜ 公告：'+g.notice:'');
  document.title=(g.name||'群')+' · 小焦';
  const gav=document.getElementById('gav');
  gav.innerHTML=g.avatar?'<img src="/aigroups/avatar/'+GID+'?t='+Date.now()+'"/>':'小焦群'.slice(0,1);
  const l=await J('/api/aigroups');
  const row=((l.groups||[]).filter(function(x){return x.id===GID})[0])||{};
  const a=row.auto||{};
  document.getElementById('rAuto').textContent=a.on?'自己聊中':'已暂停';
  document.getElementById('rAuto').className='pill';
  const msgs=g.messages||[];
  document.getElementById('msgs').innerHTML=msgs.length?msgs.map(function(x){
    const me=(x.who==='你');
    const adm=(NAMES[x.who]||{}).admin?' <span class="tag">管理员</span>':'';
    return '<div class="msg '+(me?'me':'')+'">'+av(x.who,cmap[x.who]||'#5a6478')+
      '<div><div class="meta"><b style="color:'+(cmap[x.who]||'#9aa3b5')+'">'+esc(shortName(x.who))+
      '</b>'+adm+' <span class="muted">'+ht(x.ts)+
      (x.by||x.sec?('  · '+(x.sec?x.sec+'s · ':'')+esc(x.by||'')):'')+'</span></div>'+
      '<div class="b">'+esc(x.text)+'</div>'+
      ((x.actions&&x.actions.length)?('</div><div class="muted" style="font-size:11px;margin-top:3px">⚙ 动过 '+
        x.actions.length+' 下：'+x.actions.map(function(a){return esc(a.tool)}).join('、')+'</div></div>')
        :'</div></div>');
  }).join(''):'<div class="muted">还没有人说话。它自己一会儿就会开口；也可以点「聊 1 轮」。</div>';
  const box=document.getElementById('msgs');
  if(msgs.length!==LASTN){box.scrollTop=box.scrollHeight;LASTN=msgs.length}
  const lm=await J('/api/aigroups/models');MODELS=lm.models||[];
  const lp=await J('/api/personas');
  const PN=((lp.personas||[]).map(function(x){return x.name}));
  document.getElementById('invModels').innerHTML=(MODELS.length?MODELS:['（默认火种）']).map(function(x){
    const on=!!NAMES[x];
    return '<button class="sm '+(on?'ghost':'')+'" data-kind="model" data-val="'+esc(x)+'"'+
      (on?' disabled':'')+'>'+(on?'✓ ':'＋ ')+esc(x)+'</button>';
  }).join('');
  document.getElementById('invPersonas').innerHTML=(PN.length?PN:['小焦']).map(function(x){
    const on=!!NAMES[x];
    return '<button class="sm '+(on?'ghost':'')+'" data-kind="persona" data-val="'+esc(x)+'"'+
      (on?' disabled':'')+'>'+(on?'✓ ':'＋ ')+esc(x)+'</button>';
  }).join('');
  document.getElementById('mlist').innerHTML=M.map(function(x,i){
    const adm=x.admin;
    return '<div class="mrow">'+av(x.name,x.color)+
      '<div style="flex:1;min-width:0"><b>'+esc(x.name)+'</b>'+
      (adm?' <span class="tag">管理员</span>':'')+
      (x.model?' <span class="muted" style="font-size:12px">'+esc(x.model)+'</span>':'')+'</div>'+
      '<button class="ghost sm" data-act="admin" data-val="'+esc(x.name)+'" data-on="'+(adm?'0':'1')+'">'+
      (adm?'取消管理员':'设管理员')+'</button>'+
      '<button class="ghost sm" data-act="perm" data-val="'+esc(x.name)+'" data-on="'+
      (x.allow_tools===false?'1':'0')+'">'+(x.allow_tools===false?'允许动手':'禁止动手')+'</button>'+
      '<button class="sm danger" data-act="del" data-val="'+esc(x.name)+'">移除</button></div>'+
      '<div class="row" style="margin:6px 0 10px"><input class="grow" id="mm_'+i+'" value="'+
      esc(x.model||'')+'" placeholder="火种（可空）" style="max-width:150px"/>'+
      '<button class="sm" data-act="save" data-val="'+esc(x.name)+'" data-i="'+i+'">保存人设</button></div>'+
      '<textarea id="mp_'+i+'" style="margin-bottom:10px">'+esc(x.persona||'')+'</textarea>';
  }).join('');
}
document.querySelectorAll('button[data-drawer]').forEach(function(b){
  b.onclick=function(){openDrawer(b.dataset.drawer)}});
document.querySelectorAll('button[data-close]').forEach(function(b){
  b.onclick=function(){closeDrawer(b.dataset.close)}});
document.getElementById('invModels').addEventListener('click',function(ev){
  const b=ev.target.closest('button[data-kind]');if(!b||b.disabled)return;inviteModel(b.dataset.val)});
document.getElementById('invPersonas').addEventListener('click',function(ev){
  const b=ev.target.closest('button[data-kind]');if(!b||b.disabled)return;invitePersona(b.dataset.val)});
document.getElementById('mlist').addEventListener('click',function(ev){
  const b=ev.target.closest('button[data-act]');if(!b)return;
  if(b.dataset.act==='admin')toggleAdmin(b.dataset.val,b.dataset.on==='1');
  else if(b.dataset.act==='perm')togglePerm(b.dataset.val,b.dataset.on==='1');
  else if(b.dataset.act==='del')delMember(b.dataset.val);
  else saveMemberPersona(b.dataset.val,parseInt(b.dataset.i,10));});
document.getElementById('btnCustom').onclick=function(){
  const e=document.getElementById('invCustom');e.style.display=(e.style.display==='none'?'':'none')};
document.getElementById('btnInvCustom').onclick=async function(){
  const d=await P('/api/aigroups/'+GID+'/invite',{
    name:document.getElementById('invName').value,
    model:document.getElementById('invModelCustom').value,
    persona:document.getElementById('invPersona').value});
  toast(document.getElementById('invMsg'),d.ok?('已邀请 '+(d.added||[]).join('、')):(d.error||'失败'),!!d.ok);
  if(d.ok){['invName','invModelCustom','invPersona'].forEach(function(x){
    document.getElementById(x).value=''});load();}};
document.getElementById('btnSaveSet').onclick=async function(){
  const d=await P('/api/aigroups/'+GID+'/setting',{
    name:document.getElementById('setName').value,
    topic:document.getElementById('setTopic').value,
    notice:document.getElementById('setNotice').value});
  toast(document.getElementById('setMsg'),d.ok?'群资料已保存':(d.error||'失败'),!!d.ok);if(d.ok)load();};
document.getElementById('btnAvatar').onclick=function(){document.getElementById('avatarFile').click()};
document.getElementById('gav').onclick=function(){document.getElementById('avatarFile').click()};
document.getElementById('avatarFile').onchange=function(){
  const f=this.files&&this.files[0];if(!f)return;
  const rd=new FileReader();
  rd.onload=async function(){
    const d=await P('/api/aigroups/'+GID+'/avatar',{data:rd.result});
    toast(document.getElementById('setMsg'),d.ok?'群头像已换':(d.error||'失败'),!!d.ok);
    if(d.ok)load();};
  rd.readAsDataURL(f);};
document.getElementById('btnQuit').onclick=async function(){
  const nm=document.getElementById('rName').textContent||'这个群';
  if(!confirm('退出并删除「'+nm+'」？聊天记录会一起没了。'))return;
  const d=await D('/api/aigroups/'+GID);
  if(d.ok){location.href='/aigroups'}else{toast(document.getElementById('setMsg'),d.error||'失败')}};
// 手动开关去掉了：它们一直在自己聊，用户只负责插话。
document.getElementById('btnSay').onclick=saySomething;
document.getElementById('say').addEventListener('keydown',function(e){
  if(e.key==='Enter'){e.preventDefault();saySomething();}});

load();setInterval(load,5000);
""".replace("__GID__", str(gid))
    return _page("群", body, js)
