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

/* ---- 聊天窗口：外层不滚，只有消息区滚（防止新消息时整页跳到顶部）---- */
.im{overflow:hidden}
.pane{overflow:hidden}
.pbody{overscroll-behavior:contain}
.msg{display:flex;gap:9px;margin:10px 0;align-items:flex-start}
.msg>div{flex:1 1 auto;min-width:0}
.msg .b{display:inline-block;background:var(--card2);border-radius:12px;padding:8px 12px;
width:max-content;max-width:min(100%,42em);white-space:pre-wrap;word-break:break-word;
text-align:left;min-width:2em}
.msg.me{flex-direction:row-reverse}
.msg.me>div{text-align:right}
.msg.me .b{background:#2a3560;text-align:left}
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
/* ---- 群组：居中双栏（左列表 / 右聊天）---- */
/* 【不要算高度】用整条 height:100% 链填满容器；算式在 iframe 里一定会偏 */
html,body{height:100%}
.wrap{height:100%;display:flex;flex-direction:column}
.im{display:grid;grid-template-columns:288px 1fr;gap:12px;align-items:stretch;
flex:1 1 auto;min-height:0;max-width:1080px;margin:0 auto;width:100%}
@media(max-width:860px){.im{grid-template-columns:1fr;height:auto}}
.rail{background:var(--card);border:1px solid var(--line);border-radius:16px;
display:flex;flex-direction:column;overflow:hidden}
.railhead{padding:10px;border-bottom:1px solid var(--line)}
.glist{overflow:auto;padding:6px}
.gitem{display:flex;gap:9px;align-items:center;padding:9px;border-radius:12px;cursor:pointer}
.gitem:hover{background:var(--card2)}
.gitem.on{background:#232c40}
.gav.sm{width:38px;height:38px;border-radius:11px;font-size:15px}
.ell{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-size:12px}
.badge{background:#e8475f;color:#fff;border-radius:999px;font-size:11px;padding:0 6px;
line-height:17px;min-width:17px;text-align:center}
.pane{background:var(--card);border:1px solid var(--line);border-radius:16px;
display:flex;flex-direction:column;overflow:hidden;min-height:0}
.phead{display:flex;gap:10px;align-items:center;padding:10px 12px;border-bottom:1px solid var(--line)}
.pbody{flex:1 1 auto;min-height:0;overflow:auto;padding:14px}
.pfoot{border-top:1px solid var(--line);padding:10px 12px}
.filebar{border-top:1px dashed #222a38;padding:7px 12px;display:flex;gap:8px;
align-items:center;flex-wrap:wrap}
.fchip{background:#1c2536;border:1px solid #26324a;border-radius:999px;padding:2px 10px;

/* ---- 消息：气泡要有最小宽度，别被挤成一列字 ---- */
.favatar{width:46px;height:46px;border-radius:12px;overflow:hidden;background:#2a3140;
display:flex;align-items:center;justify-content:center;font-size:19px;color:#fff;flex:0 0 auto}
.favatar img{width:100%;height:100%;object-fit:contain;display:block;background:#0f141d}
.fview{display:flex;flex-direction:column;flex:1 1 auto;min-height:0;overflow:hidden}
font-size:12px;color:#c9d4ec;text-decoration:none}
.drawer{display:none;margin:12px auto 0;max-width:1080px;background:var(--card);
border:1px solid var(--line);border-radius:16px;padding:14px}
.drawer.on{display:block}
.mrow{display:flex;align-items:center;gap:9px;padding:8px 0;border-bottom:1px dashed #222a38}
.mrow:last-child{border-bottom:0}
.tag{background:#2a3550;color:#a9b8ff;border-radius:8px;padding:1px 7px;font-size:11px}

/* ---- 页签 ---- */
.tabs{display:flex;gap:6px}
.tab{background:#1b2130;color:#cbd0dc;border:1px solid var(--line);border-radius:999px;
padding:6px 14px;font-size:14px;cursor:pointer}
.tab.on{background:var(--acc);color:#fff;border-color:var(--acc)}
.tabpane{display:none}
.notice{background:#1a2030;border-radius:10px;padding:8px 10px;color:#b9c3d6;font-size:13px}

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
// 【新消息不要跳回顶部】重绘后把消息框钉到底部；外层文档不动。
function stickBottom(box){
  if(!box)return;
  const go=function(){try{box.scrollTop=box.scrollHeight}catch(e){}};
  requestAnimationFrame(go);   // 只滚一次，不再用延时二次滚动（延时会让滚动条抖）
}
// 【重绘不打断阅读】只改内容，滚动位置按"之前是否在底部"决定：
//   在底部就跟到最新；在往回翻就原地不动。这一条是"滚动条老跳回顶部"的正解。
// 【不要闪】先比签名：消息没变就一个字都不重绘（轮询每几秒一次，重绘就会闪）。
//   变了才重绘，并按"是否贴底"决定钉到底还是原地不动。
// 单条消息的签名：发送方 + 长度 + 前 16 字。**故意不含 id / 时间** ——
// 这样"本地先显示的这条"和"服务器回来的同一条"签名一致，增量追加不会重复。
function oneSig(m){
  m=m||{};
  const who=String(m.from||m.who||'');
  const t=String(m.text||'');
  return who+'|'+t.length+'|'+t.slice(0,16);
}
function msgSig(items){
  return (items||[]).map(oneSig).join('\u0001');
}
// 【别整块重建】把一段 HTML 写进容器前先比签名字符串：没变就一个节点都不动。
function setHTML(box, html, sig){
  if(!box)return false;
  if(sig&&box.dataset.sig===sig)return false;
  box.innerHTML=html;
  if(sig)box.dataset.sig=sig;
  return true;
}
function patchMessages(box, items, html, htmlOne, sigsIn){
  if(!box)return;
  const sigs=sigsIn||(items||[]).map(oneSig);
  const prevSigs=(box.dataset.sigs||'');
  const prev=prevSigs?prevSigs.split('\u0001'):[];
  const nearBottom=(box.scrollHeight-box.scrollTop-box.clientHeight)<80;
  const keep=box.scrollTop;
  let changed=false;
  if(prev.length===sigs.length&&prev.every(function(v,i){return v===sigs[i]})){
    return;                                   // 完全没变 → 不重绘
  }
  const isExtend=prev.length>0&&sigs.length>prev.length&&
    prev.every(function(v,i){return v===sigs[i]});
  if(isExtend&&htmlOne){                      // 只是多了几条 → 只追加，不动老的
    const add=items.slice(prev.length).map(htmlOne).join('');
    if(add){box.insertAdjacentHTML('beforeend',add);changed=true;}
  }else{                                      // 历史被改写 → 才整块重建
    box.innerHTML=html;changed=true;
  }
  box.dataset.sigs=sigs.join('\u0001');
  if(changed){if(nearBottom){stickBottom(box);}else{box.scrollTop=keep;}}
}
function renderKeepScroll(box, html){
  if(!box){return;}
  const nearBottom=(box.scrollHeight-box.scrollTop-box.clientHeight)<80;
  const prev=box.scrollTop;
  box.innerHTML=html;
  if(nearBottom){stickBottom(box);}else{box.scrollTop=prev;}
}
// 【同一个人的头像到处一样】有上传的头像就显示图片，没有就退回首字色块。
//   好友列表 / 一对一聊天 / 群聊 / 朋友圈 都用这一个函数，不会再一会字母一会照片。
function avImg(name,color,size){
  const px=size||38;const c=color||'#7c6cf5';const nm=String(name||'友');
  // 方形圆角 + contain：**整张照片都显示**，不裁不切；只有没图时才显示首字
  const st='width:'+px+'px;height:'+px+'px;border-radius:10px;overflow:hidden;background:'+c+
    ';display:inline-flex;align-items:center;justify-content:center;font-size:'+Math.round(px*0.42)+
    'px;color:#fff;flex:0 0 auto;vertical-align:middle';
  return '<span style="'+st+'"><img src="/personas/avatar/'+encodeURIComponent(nm)+'?t='+Date.now()+
    '" style="width:100%;height:100%;object-fit:contain;display:block;background:#0f141d" '+
    'onerror="this.parentNode.textContent=&quot;'+esc(nm.slice(0,1))+'&quot;"/></span>';
}
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
def _moments_inner():
    body = """
<div class="row"><h1>🌤️ 朋友圈</h1><span class="grow"></span>
  <a href="/aigroups">👥 模型群组</a> <a href="/">← 回到单聊</a></div>
<div class="sub">**它自己会发**：后台每隔几分钟读一次它自己的状态（情绪 / 精力 / 没说出口的话 /
刚跟你聊过的事 / 逛世界看到的），够想说了就发一条 —— 每条下面都写着它当时为什么想说。
你也可以催它发（右边那两个按钮），但它照样按自己的状态说，不会被套成模板。</div>

<div class="card">
  <div class="row" id="authorRow" style="margin-bottom:10px"></div>
  <div class="row">
    <select id="postAs" style="max-width:170px"></select>
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
  <div style="margin-top:8px"><input id="pRelation" placeholder="关系/身份（例如：女朋友、室友、搭档…你自己定）"/></div>
  <div class="row" style="margin-top:10px"><button id="btnP">保存人设</button>
    <button class="ghost sm" id="btnPAvatar">上传这个 AI 的头像</button>
    <span class="muted" id="pmsg"></span></div>
  <input type="file" id="pAvatarFile" accept="image/*" style="display:none"/>
</div>
"""
    js = """
async function load(){
  const _af=window._authorFilter||'全部';
  const d=await J('/api/moments?limit=30'+((_af&&_af!=='全部')?('&author='+encodeURIComponent(_af)):''));
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
    const P=p.author||'小焦';
    const pa=PSN.filter(function(x){return x.name===P})[0]||{};
    const avt=avImg(P,pa.color,38);
    return '<div class="card mpost">'+avt+'<div class="body">'+
      '<div class="row"><span class="mname">'+esc(P)+'</span>'+
      (pa.relation?'<span class="tag">'+esc(pa.relation)+'</span>':'')+
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
  // 作者筛选 + 指定发帖人（每个 AI 有自己的动态）
  const PSN=d.personas||[];
  const authors=['全部'].concat(PSN.map(function(x){return x.name}));
  document.getElementById('authorRow').innerHTML=authors.map(function(a){
    const on=((window._authorFilter||'全部')===a);
    return '<button class="sm '+(on?'':'ghost')+'" data-author="'+esc(a)+'">'+
      (on?'✓ ':'')+esc(a)+'</button>'}).join('');
  document.getElementById('authorRow').querySelectorAll('button[data-author]').forEach(function(b){
    b.onclick=function(){window._authorFilter=(b.dataset.author==='全部'?'全部':b.dataset.author);load()}});
  const sel=document.getElementById('postAs');
  if(sel&&!sel.dataset.done){sel.dataset.done='1';
    sel.innerHTML=PSN.map(function(x){return '<option value="'+esc(x.name)+'">'+esc(x.name)+
      (x.relation?('（'+esc(x.relation)+'）'):'')+'</option>'}).join('')}
  const ps=PSN[0]||{};
  if(ps&&!window._pTouched){document.getElementById('pName').value=ps.name||'小焦';
    document.getElementById('pModel').value=ps.model||'';document.getElementById('pText').value=ps.persona||'';
    document.getElementById('pRelation').value=ps.relation||''}
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
document.getElementById('btnPAvatar').onclick=function(){
  document.getElementById('pAvatarFile').click()};
document.getElementById('pAvatarFile').onchange=function(){
  const f=this.files&&this.files[0];if(!f)return;
  const nm=(document.getElementById('pName').value||'小焦');
  const rd=new FileReader();
  rd.onload=async function(){
    const d=await P('/api/personas/avatar',{name:nm,data:rd.result});
    toast(document.getElementById('pmsg'),d.ok?'头像已换':(d.error||'失败'),!!d.ok);if(d.ok)load()};
  rd.readAsDataURL(f);this.value='';};
document.getElementById('btnPostImg').onclick=()=>post(true);
async function post(img){const b=document.getElementById('btnPost');b.disabled=true;
  toast(document.getElementById('msg'),'它在想写什么…',true);
  const sel=document.getElementById('postAs');
  const d=await P('/api/moments/post',{ask:true,with_image:img,
    author:(sel&&sel.value)||'小焦'});
  b.disabled=false;toast(document.getElementById('msg'),
    d.ok?('已发：'+(d.why||'')):(d.error||'没发成'),!!d.ok);load()}
document.getElementById('pText').oninput=()=>{window._pTouched=true};
document.getElementById('btnP').onclick=async()=>{const d=await P('/api/personas',{
  name:document.getElementById('pName').value||'小焦',
  persona:document.getElementById('pText').value,
  relation:document.getElementById('pRelation').value,
  model:document.getElementById('pModel').value});
  toast(document.getElementById('pmsg'),d.ok?'人设已保存':'保存失败：'+(d.error||''),!!d.ok)};
load();setInterval(load,20000);
"""
    return body, js


def moments_html():
    b, j = _moments_inner()
    return _page("朋友圈", b, j)


# ==================== 模型群组（独立页面）====================
def _groups_inner():
    body = """
<div class="row"><h1>👥 模型群组</h1><span class="grow"></span>
  <a href="/moments">🌤️ 朋友圈</a> <a href="/">← 回到单聊</a></div>
<div class="sub">左边是各个群（红点 = 有新消息），点一下就在右边打开；它们一直在自己聊，
不同群同时都在长消息。群里能传文件，AI 自己写出来的文件也会出现在群文件里。</div>

<div class="im">
  <div class="rail">
    <div class="railhead">
      <input id="gName" placeholder="新群名字"/>
      <input id="gTopic" placeholder="主题（可空）" style="margin-top:6px"/>
      <div class="row" style="margin-top:6px">
        <select id="gPace" style="max-width:120px">
          <option value="mixed">混合</option>
          <option value="chat">聊天群</option>
          <option value="dev">开发群</option>
        </select>
        <button class="sm" id="btnG">建群</button>
      </div>
      <div class="muted" id="gmsg" style="margin-top:5px"></div>
    </div>
    <div class="glist" id="glist"></div>
  </div>

  <div class="pane">
    <div class="phead">
      <div class="gav" id="pav">焦</div>
      <div style="flex:1;min-width:0">
        <div class="row"><b id="pName">选一个群</b><span class="pill" id="pPace"></span></div>
        <div class="muted" id="pSub" style="font-size:12px">左边点一个群进来</div>
      </div>
      <button class="sm" data-drawer="inv">＋ 邀请</button>
      <button class="ghost sm" data-drawer="mem">成员</button>
      <button class="ghost sm" data-drawer="files">文件</button>
      <button class="ghost sm" data-drawer="set">设置</button>
    </div>

    <div class="pbody" id="msgs"><div class="muted">左边点一个群进来。</div></div>

    <div class="filebar" id="filebar"></div>

    <div class="pfoot">
      <div class="row"><input class="grow" id="say" placeholder="说点什么…（它们自己也会聊，不用你催）"/>
        <button id="btnSay">发送</button></div>
      <div class="muted" id="cmsg" style="margin-top:6px"></div>
    </div>
  </div>
</div>

<!-- 抽屉：邀请 -->
<div class="drawer" id="d-inv">
  <div class="row"><b>邀请模型进群</b><span class="muted">（点一下就邀，不用打字）</span>
    <span class="grow"></span><button class="ghost sm" data-close="inv">收起</button></div>
  <div class="muted" style="margin-top:8px">按火种</div>
  <div class="row" id="invModels" style="margin-top:6px"></div>
  <div class="muted" style="margin-top:10px">按人设</div>
  <div class="row" id="invPersonas" style="margin-top:6px"></div>
  <div class="muted" id="invMsg" style="margin-top:8px"></div>
</div>

<!-- 抽屉：成员 -->
<div class="drawer" id="d-mem">
  <div class="row"><b>群成员</b><span class="muted">（可设管理员 / 允许动手 / 换火种 / 移除）</span>
    <span class="grow"></span><button class="ghost sm" data-close="mem">收起</button></div>
  <div class="muted" style="margin-top:6px;font-size:12px">
    这里的「小焦 / 阿码 / 老曲」是**角色**，不是模型：建群时自带的三个人设。
    没绑火种的用当前默认火种（现在就是 xiaojiao1.0-4B）—— 所以它们同一个脑子、靠不同人设说话。
    想让某个角色更聪明/更会说，就点下面那排火种，给它单独绑一颗。</div>
  <div id="mlist" style="margin-top:8px"></div>
</div>

<!-- 抽屉：文件 -->
<div class="drawer" id="d-files">
  <div class="row"><b>群文件</b><span class="muted">（一起看、一起讨论）</span>
    <span class="grow"></span>
    <button class="sm" id="btnUp">上传文件</button>
    <button class="ghost sm" data-close="files">收起</button></div>
  <input type="file" id="fileInput" style="display:none"/>
  <div id="flist" style="margin-top:10px"></div>
  <div class="muted" id="fmsg" style="margin-top:8px"></div>
</div>

<!-- 抽屉：设置 -->
<div class="drawer" id="d-set">
  <div class="row"><b>群设置</b><span class="grow"></span>
    <button class="ghost sm" data-close="set">收起</button></div>
  <div style="margin-top:9px"><input id="setName" placeholder="群名"/></div>
  <div style="margin-top:8px"><input id="setTopic" placeholder="主题"/></div>
  <div style="margin-top:8px"><input id="setNotice" placeholder="群公告"/></div>
  <div class="muted" style="margin-top:12px">群节奏（决定它们多爱动手）</div>
  <div class="row" id="paceRow" style="margin-top:6px"></div>
  <div class="muted" style="margin-top:12px">本群共识（每轮自动蒸馏）</div>
  <div id="distillBox" class="notice" style="margin-top:6px"></div>
  <div class="row" style="margin-top:10px"><button class="sm" id="btnSaveSet">保存群资料</button>
    <button class="ghost sm" id="btnAvatar">上传群头像</button>
    <button class="sm danger" id="btnQuit">退出群</button></div>
  <input type="file" id="avatarFile" accept="image/*" style="display:none"/>
  <div class="muted" id="setMsg" style="margin-top:6px"></div>
</div>
"""

    js = """
let CUR='',LASTN=0,GROUPS=[],DETAIL=null;
function toast(el,m,ok){if(!el)return;el.textContent=m;el.className=ok?'ok':'err';
  setTimeout(function(){if(el.textContent===m)el.textContent=''},4000)}
function openDrawer(k){['inv','mem','files','set'].forEach(function(x){
  document.getElementById('d-'+x).classList.toggle('on',x===k)});
  if(k==='set')fillSettings();}
function closeDrawer(k){document.getElementById('d-'+k).classList.remove('on')}
async function loadList(){
  const d=await J('/api/aigroups');GROUPS=d.groups||[];
  const box=document.getElementById('glist');
  box.innerHTML=GROUPS.length?GROUPS.map(function(g){
    const un=g.unread||0;
    return '<div class="gitem '+(g.id===CUR?'on':'')+'" data-gid="'+g.id+'">'+
      '<div class="gav sm">'+esc((g.name||'群').slice(0,1))+'</div>'+
      '<div style="flex:1;min-width:0">'+
        '<div class="row"><b style="font-size:14px">'+esc(g.name)+'</b>'+
        (un?'<span class="badge">'+(un>99?'99+':un)+'</span>':'')+'</div>'+
        '<div class="muted ell">'+esc((g.last_who?g.last_who+'：':'')+(g.last||g.topic||'—'))+'</div>'+
      '</div></div>';
  }).join(''):'<div class="muted" style="padding:10px">还没有群，上面建一个。</div>';
}
async function openGroup(gid){
  CUR=gid;
  try{await P('/api/aigroups/'+gid+'/read',{})}catch(e){}
  await loadList();await loadChat();
}
async function loadChat(){
  if(!CUR)return;
  const d=await J('/api/aigroups/'+CUR);
  if(!d.ok)return;
  const g=d.group||{};DETAIL=g;
  document.getElementById('pName').textContent=g.name||'';
  document.title=(g.name||'群')+' · 小焦';
  document.getElementById('pPace').textContent=({chat:'聊天群',mixed:'混合',dev:'开发群'})[g.pace||'mixed'];
  document.getElementById('pSub').textContent=(g.topic||'无主题')+' ｜ '+(g.members||[]).length+' 人'+
    ((g.files||[]).length?(' ｜ 文件 '+(g.files||[]).length):'');
  const pav=document.getElementById('pav');
  pav.innerHTML=g.avatar?'<img src="/aigroups/avatar/'+CUR+'?t='+Date.now()+'"/>':esc((g.name||'焦').slice(0,1));
  const M=g.members||[];const cmap={};const mm={};
  M.forEach(function(x){cmap[x.name]=x.color;mm[x.name]=x});
  const msgs=g.messages||[];
  const gOneHtml=function(x){
    const me=(x.who==='你');
    const adm=(mm[x.who]||{}).admin?' <span class="tag">管理员</span>':'';
    const meta=ht(x.ts)+(x.sec?(' · '+x.sec+'s'):'')+
      ((x.by&&x.by!=='user')?(' · 火种 '+esc(x.by)):'');
    const isDefault=(!me)&&(!((mm[x.who]||{}).model));
    const acts=(x.actions&&x.actions.length)?
      ('<div class="muted" style="font-size:11px;margin-top:3px">⚙ 动过 '+x.actions.length+
       ' 下：'+x.actions.map(function(a){return esc(a.tool)}).join('、')+'</div>'):'';
    return '<div class="msg '+(me?'me':'')+'>'+avImg(x.who,cmap[x.who]||'#5a6478',34)+
      '<div><div class="meta"><b style="color:'+(cmap[x.who]||'#9aa3b5')+'">'+
      esc(shortName(x.who))+'</b>'+adm+
      (isDefault?' <span class="tag">默认角色</span>':'')+
      ' <span class="muted">'+meta+'</span></div>'+
      '<div class="b" style="width:max-content;max-width:min(100%,42em);white-space:pre-wrap;word-break:break-word;text-align:left;min-width:2em">'+esc(x.text)+'</div>'+acts+'</div></div>';
  }; const _mhtml=msgs.length?msgs.map(gOneHtml).join(''):'<div class="muted">还没有人说话。它们自己一会儿就开口。</div>';
  const box=document.getElementById('msgs');
  patchMessages(box,msgs,_mhtml,gOneHtml);LASTN=msgs.length;
  // 红点：进来就算已读
  if((GROUPS.filter(function(x){return x.id===CUR})[0]||{}).unread)loadList();
  // 群文件条
  const fs=g.files||[];
  const _fbSig=JSON.stringify(fs.map(function(f){return [f.id,f.name,f.by]}));
  setHTML(document.getElementById('filebar'),fs.length?(
    '<span class="muted" style="font-size:12px">群文件：</span>'+
    fs.slice(-6).map(function(f){
      return '<a class="fchip" href="/api/aigroups/'+CUR+'/file/'+f.id+'" target="_blank" '+
        'title="'+esc(f.by||'')+' 上传">📄 '+esc(f.name)+'</a>'}).join('')):
    '<span class="muted" style="font-size:12px">还没有群文件（可以自己传，AI 写出的文件也会出现在这）</span>',_fbSig);
  // 邀请抽屉要先知道有哪些火种（成员行的火种点选也用这一份）
  const names={};M.forEach(function(x){names[x.name]=1});
  const lm=await J('/api/aigroups/models');const MODELS=lm.models||[];
  // 成员抽屉（火种用点选，不打字）
  const _mlSig=JSON.stringify(M.map(function(x){return [x.name,x.model,x.admin,x.allow_tools,x.persona]}))+MODELS.join(',');
  setHTML(document.getElementById('mlist'),M.map(function(x,i){
    const adm=x.admin;const allow=(x.allow_tools!==false);
    const cur=String(x.model||'');
    const chips=[''].concat(MODELS).map(function(mv){
      const on=(mv===cur);
      const lab=mv?mv:'默认火种';
      return '<button class="sm '+(on?'':'ghost')+'" data-act="setmodel" data-val="'+esc(x.name)+
        '" data-model="'+esc(mv)+'">'+(on?'✓ ':'')+esc(lab)+'</button>'}).join('');
    return '<div class="mrow" style="flex-wrap:wrap">'+av(x.name,x.color)+
      '<div style="flex:1;min-width:0"><b>'+esc(shortName(x.name))+'</b>'+
      (adm?' <span class="tag">管理员</span>':'')+
      (allow?'':' <span class="tag" style="background:#3a2230;color:#ff9db0">不许动手</span>')+
      '<div class="muted" style="font-size:12px">火种：'+esc(cur||'默认')+'</div></div>'+
      '<button class="ghost sm" data-act="admin" data-val="'+esc(x.name)+'" data-on="'+(adm?'0':'1')+'">'+
      (adm?'取消管理员':'设管理员')+'</button>'+
      '<button class="ghost sm" data-act="perm" data-val="'+esc(x.name)+'" data-on="'+(allow?'0':'1')+'">'+
      (allow?'禁止动手':'允许动手')+'</button>'+
      '<button class="sm danger" data-act="del" data-val="'+esc(x.name)+'">移除</button>'+
      '<div class="row" style="width:100%;margin-top:6px">'+chips+'</div></div>';
  }).join(''),_mlSig);
  const lp=await J('/api/personas');const PN=((lp.personas||[]).map(function(x){return x.name}));
  const _invSig=MODELS.join(',')+'|'+Object.keys(names).join(',');
  setHTML(document.getElementById('invModels'),(MODELS.length?MODELS:['（默认火种）']).map(function(x){
    const on=!!names[x];
    return '<button class="sm '+(on?'ghost':'')+'" data-kind="model" data-val="'+esc(x)+'"'+
      (on?' disabled':'')+'>'+(on?'✓ ':'＋ ')+esc(x)+'</button>'}).join(''), _invSig);
  setHTML(document.getElementById('invPersonas'),(PN.length?PN:['小焦']).map(function(x){
    const on=!!names[x];
    return '<button class="sm '+(on?'ghost':'')+'" data-kind="persona" data-val="'+esc(x)+'"'+
      (on?' disabled':'')+'>'+(on?'✓ ':'＋ ')+esc(x)+'</button>'}).join(''), 'p|'+PN.join(',')+'|'+Object.keys(names).join(','));
  // 文件抽屉
  document.getElementById('flist').innerHTML=fs.length?fs.slice().reverse().map(function(f){
    return '<div class="mrow"><span style="flex:1;min-width:0">📄 <a href="/api/aigroups/'+CUR+
      '/file/'+f.id+'" target="_blank">'+esc(f.name)+'</a>'+
      '<div class="muted" style="font-size:12px">'+esc(f.by||'')+' ｜ '+Math.round((f.size||0)/1024)+
      'KB ｜ '+esc(f.ts||'')+'</div></span></div>'}).join(''):
    '<div class="muted">还没有文件。上传一个，它们会围着它讨论。</div>';
}
async function sendSay(){
  const el=document.getElementById('say');const t=(el.value||'').trim();if(!t||!CUR)return;
  const d=await P('/api/aigroups/'+CUR+'/say',{text:t});
  if(!d.ok){toast(document.getElementById('cmsg'),d.error);return}
  el.value='';loadChat();
}
const PACES=[['chat','聊天群'],['mixed','混合'],['dev','开发群']];
async function fillSettings(){
  if(!CUR||!DETAIL)return;const g=DETAIL;
  document.getElementById('setName').value=g.name||'';
  document.getElementById('setTopic').value=g.topic||'';
  document.getElementById('setNotice').value=g.notice||'';
  const cur=g.pace||'mixed';
  document.getElementById('paceRow').innerHTML=PACES.map(function(x){
    return '<button class="sm '+(x[0]===cur?'':'ghost')+'" data-pace="'+x[0]+'">'+
      (x[0]===cur?'✓ ':'')+x[1]+'</button>'}).join('');
  document.getElementById('paceRow').querySelectorAll('button[data-pace]').forEach(function(b){
    b.onclick=async function(){
      const d=await P('/api/aigroups/'+CUR+'/pace',{pace:b.dataset.pace});
      toast(document.getElementById('setMsg'),d.ok?'节奏已切':'失败',!!d.ok);loadChat();}});
  const ds=g.distilled||[];
  document.getElementById('distillBox').innerHTML=ds.length?
    ds.slice(-6).map(function(x){return '· '+esc(x.note||'')}).join('<br>'):
    '（还没有。聊几轮就会自己蒸馏出来）';
}
document.getElementById('glist').addEventListener('click',function(ev){
  const it=ev.target.closest('[data-gid]');if(!it)return;openGroup(it.dataset.gid);
});
document.querySelectorAll('button[data-drawer]').forEach(function(b){
  b.onclick=function(){openDrawer(b.dataset.drawer)}});
document.querySelectorAll('button[data-close]').forEach(function(b){
  b.onclick=function(){closeDrawer(b.dataset.close)}});
document.getElementById('invModels').addEventListener('click',async function(ev){
  const b=ev.target.closest('button[data-kind]');if(!b||b.disabled||!CUR)return;
  const d=await P('/api/aigroups/'+CUR+'/invite',{model:b.dataset.val});
  toast(document.getElementById('invMsg'),d.ok?'已邀请':'失败',!!d.ok);if(d.ok)loadChat();});
document.getElementById('invPersonas').addEventListener('click',async function(ev){
  const b=ev.target.closest('button[data-kind]');if(!b||b.disabled||!CUR)return;
  const d=await P('/api/aigroups/'+CUR+'/invite',{name:b.dataset.val});
  toast(document.getElementById('invMsg'),d.ok?'已邀请':'失败',!!d.ok);if(d.ok)loadChat();});
document.getElementById('mlist').addEventListener('click',async function(ev){
  const b=ev.target.closest('button[data-act]');if(!b||!CUR)return;
  const act=b.dataset.act,v=b.dataset.val;
  let d;
  if(act==='setmodel')d=await P('/api/aigroups/'+CUR+'/member',{member:v,model:b.dataset.model});
  else if(act==='admin')d=await P('/api/aigroups/'+CUR+'/admin',{name:v,on:b.dataset.on==='1'});
  else if(act==='perm')d=await P('/api/aigroups/'+CUR+'/perm',{name:v,allow_tools:b.dataset.on==='1'});
  else d=await P('/api/aigroups/'+CUR+'/member/remove',{name:v});
  toast(document.getElementById('cmsg'),d.ok?'已处理':(d.error||'失败'),!!d.ok);if(d.ok)loadChat();});
document.getElementById('btnSay').onclick=sendSay;
document.getElementById('say').addEventListener('keydown',function(e){
  if(e.key==='Enter'){e.preventDefault();sendSay();}});
document.getElementById('btnUp').onclick=function(){document.getElementById('fileInput').click()};
document.getElementById('fileInput').onchange=function(){
  const f=this.files&&this.files[0];if(!f||!CUR)return;
  const rd=new FileReader();
  rd.onload=async function(){
    const d=await P('/api/aigroups/'+CUR+'/file',{name:f.name,data:rd.result});
    toast(document.getElementById('fmsg'),d.ok?('已上传 '+f.name):(d.error||'失败'),!!d.ok);
    if(d.ok){loadChat();openDrawer('files')}};
  rd.readAsDataURL(f);this.value='';};
document.getElementById('btnG').onclick=async function(){
  const nm=(document.getElementById('gName').value||'').trim();
  if(!nm){toast(document.getElementById('gmsg'),'先给群起个名字');return}
  const d=await P('/api/aigroups',{name:nm,topic:document.getElementById('gTopic').value,
    pace:document.getElementById('gPace').value,members:[]});
  if(!d.ok){toast(document.getElementById('gmsg'),d.error||'建群失败');return}
  document.getElementById('gName').value='';document.getElementById('gTopic').value='';
  toast(document.getElementById('gmsg'),'建好了',true);
  await loadList();openGroup(d.group.id);};
document.getElementById('btnSaveSet').onclick=async function(){
  if(!CUR)return;
  const d=await P('/api/aigroups/'+CUR+'/setting',{name:document.getElementById('setName').value,
    topic:document.getElementById('setTopic').value,notice:document.getElementById('setNotice').value});
  toast(document.getElementById('setMsg'),d.ok?'已保存':(d.error||'失败'),!!d.ok);if(d.ok)loadChat();};
document.getElementById('btnAvatar').onclick=function(){document.getElementById('avatarFile').click()};
document.getElementById('avatarFile').onchange=function(){
  const f=this.files&&this.files[0];if(!f||!CUR)return;
  const rd=new FileReader();
  rd.onload=async function(){
    const d=await P('/api/aigroups/'+CUR+'/avatar',{data:rd.result});
    toast(document.getElementById('setMsg'),d.ok?'群头像已换':(d.error||'失败'),!!d.ok);if(d.ok)loadChat();};
  rd.readAsDataURL(f);this.value='';};
document.getElementById('btnQuit').onclick=async function(){
  if(!CUR)return;
  const nm=document.getElementById('pName').textContent||'这个群';
  if(!confirm('退出并删除「'+nm+'」？聊天记录会一起没了。'))return;
  const d=await D('/api/aigroups/'+CUR);
  if(d.ok){CUR='';location.reload()}else{toast(document.getElementById('setMsg'),d.error||'失败')}};
(async function boot(){
  await loadList();
  const q=new URLSearchParams(location.search).get('gid');
  const want=q||(GROUPS[0]&&GROUPS[0].id);
  if(want){const it=document.getElementById('glist').querySelector('[data-gid="'+want+'"]');
    if(it)it.click();else openGroup(want)}
  setInterval(async function(){await loadList();await loadChat()},4000);
})();
"""
    return body, js


def groups_html():
    b, j = _groups_inner()
    return _page("模型群组", b, j)


# ==================== 好友（一对一）====================
def _friends_inner():
    """好友：左列表 + 右聊天 + 他的朋友圈 + 定义角色。

    ⚠️ 这里所有 id 都带 `fr_` 前缀：好友页和群组页**同处一个页面**，
       之前两边都叫 `flist`，群组那段脚本把「还没有文件…」写进了好友列表（截图事故）。
    """
    body = """
<div class="im">
  <div class="rail">
    <div class="railhead">
      <div class="row" style="flex-wrap:nowrap"><b style="font-size:14px;white-space:nowrap">好友</b>
        <span class="grow"></span>
        <button class="sm" id="fr_new">＋ 新好友</button></div>
      <div class="muted" style="font-size:12px;margin-top:4px">他们会自己找你说话</div>
    </div>
    <div class="glist" id="fr_list"></div>
  </div>
  <div class="pane">
    <div class="phead" style="flex-wrap:nowrap">
      <div class="favatar" id="fr_avatar" style="width:46px;height:46px;flex:0 0 auto">友</div>
      <div style="flex:1;min-width:0">
        <div class="row" style="flex-wrap:nowrap"><b id="fr_name" style="white-space:nowrap">还没有好友</b>
          <span class="tag" id="fr_rel" style="display:none"></span></div>
        <div class="muted" id="fr_sub" style="font-size:12px;white-space:nowrap;overflow:hidden;
             text-overflow:ellipsis">点左上「＋ 新好友」定义一个人</div>
      </div>
      <button class="ghost sm" data-fview="chat" style="white-space:nowrap">聊天</button>
      <button class="ghost sm" data-fview="moments" style="white-space:nowrap">他的朋友圈</button>
      <button class="ghost sm" data-fview="set" style="white-space:nowrap">定义角色</button>
    </div>

    <div class="fview" id="fr_v_chat">
      <div class="pbody" id="fr_msgs"><div class="muted">左边选一个好友。</div></div>
    </div>

    <div class="fview" id="fr_v_moments" style="display:none">
      <div class="pbody" id="fr_moments"><div class="muted">他的朋友圈是**他自己发的**：你只能看、点赞、评论。</div></div>
    </div>

    <div class="fview" id="fr_v_set" style="display:none">
      <div class="pbody">
        <div class="muted" style="font-size:13px">定义一次，他就是一个"人"：有自己的性格、关系、头像，
          有自己的朋友圈，会主动找你说话。</div>
        <div style="margin-top:10px"><input id="fr_dname" placeholder="名字（例如：小美）"/></div>
        <div style="margin-top:8px"><input id="fr_drel" placeholder="关系/身份（女朋友、室友、搭档…你定）"/></div>
        <div style="margin-top:8px"><input id="fr_dmodel" placeholder="火种（可空=默认）"/></div>
        <textarea id="fr_dpersona" placeholder="他的性格：说话方式、在意什么、习惯…" style="margin-top:8px"></textarea>
        <div class="row" style="margin-top:10px">
          <button class="sm" id="fr_save">保存这个好友</button>
          <button class="ghost sm" id="fr_avatar_btn">上传他的头像</button>
          <span class="muted" id="fr_dmsg"></span>
        </div>
        <input type="file" id="fr_avatar_file" accept="image/*" style="display:none"/>
      </div>
    </div>

    <!-- 输入框固定在面板底部（不放在任何 fview 里） -->
    <div class="pfoot" id="fr_foot">
      <div class="row"><input class="grow" id="fr_say" placeholder="跟他说点什么…（他不回你也会自己找你）"/>
        <button id="fr_send">发送</button></div>
      <div class="muted" id="fr_msg" style="margin-top:6px"></div>
    </div>
  </div>
</div>
"""
    js = """
let FRCUR='',FRFRIENDS=[],FRHIST=[];
function frToast(m,ok){const el=document.getElementById('fr_msg');
  if(!el)return;el.textContent=m;el.className=ok?'ok':'err';
  setTimeout(function(){if(el.textContent===m)el.textContent=''},4000)}
function frShow(v){
  ['chat','moments','set'].forEach(function(x){
    const el=document.getElementById('fr_v_'+x);if(!el)return;
    el.style.display=(x===v)?(x==='chat'?'flex':'block'):'none';
  });
  const foot=document.getElementById('fr_foot');
  if(foot)foot.style.display=(v==='chat')?'':'none';   // 只在聊天视图显示输入框
}
document.querySelectorAll('button[data-fview]').forEach(function(b){
  b.onclick=function(){frShow(b.dataset.fview)}});
function frAv(name,avatar,color,size){
  const st='width:'+(size||38)+'px;height:'+(size||38)+'px;border-radius:11px;overflow:hidden;'+
    'background:'+(color||'#2a3140')+';display:inline-flex;align-items:center;'+
    'justify-content:center;font-size:15px;color:#fff;flex:0 0 auto';
  return '<span style="'+st+'">'+(avatar?
    '<img src="/personas/avatar/'+encodeURIComponent(name)+'?t='+Date.now()+
    '" style="width:100%;height:100%;object-fit:cover"/>':esc((name||'友').slice(0,1)))+'</span>';
}
async function frLoadList(){
  const d=await J('/api/friends');FRFRIENDS=d.friends||[];
  const box=document.getElementById('fr_list');
  const _sig=JSON.stringify(FRFRIENDS.map(function(f){
    return [f.name,f.unread,f.last,f.last_from,f.avatar,f.relation]}));
  if(box.dataset.sig===_sig)return;      // 列表没变化 → 不重绘
  box.dataset.sig=_sig;
  box.innerHTML=FRFRIENDS.length?FRFRIENDS.map(function(f){
    const un=f.unread||0;
    return '<div class="gitem '+(f.name===FRCUR?'on':'')+'" data-fname="'+esc(f.name)+'">'+
      avImg(f.name,f.color,36)+
      '<div style="flex:1;min-width:0"><div class="row" style="flex-wrap:nowrap">'+
      '<b style="font-size:14px;white-space:nowrap">'+esc(f.name)+'</b>'+
      (un?'<span class="badge">'+(un>99?'99+':un)+'</span>':'')+'</div>'+
      '<div class="muted ell">'+esc((f.last_from==='friend'?'他：':'你：')+(f.last||f.relation||'—'))+
      '</div></div></div>';
  }).join(''):'<div class="muted" style="padding:10px">还没有好友。点上面「＋ 新好友」定义一个人。</div>';
}
document.getElementById('fr_list').addEventListener('click',function(ev){
  const it=ev.target.closest('[data-fname]');if(!it)return;frOpen(it.dataset.fname);
});
async function frOpen(name){
  FRCUR=name;frShow('chat');await frLoadList();
  try{await P('/api/friends/'+encodeURIComponent(name)+'/read',{})}catch(e){}
  const d=await J('/api/friends/'+encodeURIComponent(name));
  if(!d.ok)return;
  const f=d.friend||{};
  document.getElementById('fr_name').textContent=f.name||name;
  const rel=document.getElementById('fr_rel');
  if(f.relation){rel.textContent=f.relation;rel.style.display=''}else{rel.style.display='none'}
  document.getElementById('fr_sub').textContent=(f.persona||'还没写性格').slice(0,40)+
    ' ｜ 动态 '+((d.moments||[]).length)+' 条';
  document.getElementById('fr_avatar').innerHTML=f.avatar?
    '<img src="/personas/avatar/'+encodeURIComponent(name)+'?t='+Date.now()+
    '" style="width:100%;height:100%;object-fit:cover"/>':esc((f.name||'友').slice(0,1));
  const hs=d.history||[];
  FRHIST=hs;
  const frOneHtml=function(m){
    const me=(m.from==='user');
    const tag=(!me&&m.why&&m.why!=='回你')?' <span class="tag">他主动找你</span>':'';
    const head=me?avImg('你','#3d5afe',38):avImg(f.name||name,f.color,38);
    return '<div class="msg '+(me?'me':'')+'">'+head+'<div><div class="meta">'+
      '<b>'+esc(me?'你':(f.name||name))+'</b>'+tag+
      '<span class="muted">'+ht(m.ts)+(m.by?(' · 火种 '+esc(m.by)):'')+'</span></div>'+
      '<div class="b" style="width:max-content;max-width:min(100%,42em);white-space:pre-wrap;word-break:break-word;text-align:left;min-width:2em">'+
      esc(m.text)+'</div></div></div>';
  }; const _fhtml=hs.length?hs.map(frOneHtml).join(''):'<div class="muted">还没聊过。他可能会自己先开口，你也可以先说。</div>';
  const box=document.getElementById('fr_msgs');patchMessages(box,hs,_fhtml,frOneHtml);
  const ms=d.moments||[];
  document.getElementById('fr_moments').innerHTML=ms.length?ms.map(function(p){
    const cm=(p.comments||[]).map(function(c){
      return '<div class="cmt"><b>'+esc(c.who)+'</b>：'+esc(c.text)+
        (c.reply?'<div class="reply">↳ '+esc(c.reply)+'</div>':'')+'</div>'}).join('');
    return '<div class="card" style="background:var(--card2)">'+
      '<div class="row"><b>'+esc(p.author)+'</b><span class="muted">'+ht(p.ts)+'</span>'+
      '<span class="grow"></span><span class="pill">'+esc(p.why||'自己想发的')+'</span></div>'+
      '<div class="mtext">'+esc(p.text)+'</div>'+
      '<div class="likebar"><span style="cursor:pointer" data-likeid="'+p.id+'">❤️ '+
      (p.likes||[]).length+'</span><span>💬 '+(p.comments||[]).length+'</span></div>'+
      (cm||'')+
      '<div class="row" style="margin-top:8px"><input class="grow" id="fr_c_'+p.id+'" placeholder="评一句…"/>'+
      '<button class="sm" data-cmtid="'+p.id+'">评论</button></div></div>';
  }).join(''):'<div class="muted">他还没发过动态。**他自己会发**，不用你催。</div>';
  document.getElementById('fr_moments').querySelectorAll('[data-likeid]').forEach(function(el){
    el.onclick=async function(){await P('/api/moments/like',{id:el.dataset.likeid,who:'你'});frOpen(FRCUR)}});
  document.getElementById('fr_moments').querySelectorAll('[data-cmtid]').forEach(function(b){
    b.onclick=async function(){
      const el=document.getElementById('fr_c_'+b.dataset.cmtid);const t=(el.value||'').trim();if(!t)return;
      const r=await P('/api/moments/comment',{id:b.dataset.cmtid,text:t,who:'你'});
      const rp=(r.reply||{});
      frToast(rp.replied?('他回了：'+(rp.text||'')):('评论发出了。他这次没回 —— '+(rp.why||'')),true);
      frOpen(FRCUR)}});
  document.getElementById('fr_dname').value=f.name||name;
  document.getElementById('fr_drel').value=f.relation||'';
  document.getElementById('fr_dmodel').value=f.model||'';
  document.getElementById('fr_dpersona').value=f.persona||'';
}
async function frSay(){
  const el=document.getElementById('fr_say');const t=(el.value||'').trim();if(!t||!FRCUR)return;
  el.value='';
  // 【先显示你这条】不等模型回，先把气泡画出来（不然要刷新才看见）
  const box=document.getElementById('fr_msgs');
  const f=(FRFRIENDS.filter(function(x){return x.name===FRCUR})[0])||{};
  box.insertAdjacentHTML('beforeend','<div class="msg me">'+avImg('你','#3d5afe',34)+
    '<div><div class="meta"><b>你</b><span class="muted">'+ht(new Date().toISOString())+
    '</span></div><div class="b" style="width:max-content;max-width:min(100%,42em);white-space:pre-wrap;word-break:break-word;text-align:left;min-width:2em">'+esc(t)+
    '</div></div></div>');
  stickBottom(box);
  frToast('他在想怎么回…',true);
  const d=await P('/api/friends/'+encodeURIComponent(FRCUR)+'/say',{text:t});
  if(!d.ok){frToast(d.error||'发送失败');return}
  frToast(d.reply?'他回了':('他这次没回：'+((d.why)||'')),true);
  // 【不再回拉一次】POST 已经把"他那句"带回来了，直接追加，少一次请求就少一次重绘
  if(d.reply&&d.reply.text){
    const box2=document.getElementById('fr_msgs');
    const f2=(FRFRIENDS.filter(function(x){return x.name===FRCUR})[0])||{};
    const one='<div class="msg">'+avImg(FRCUR,f2.color,34)+'<div><div class="meta"><b>'+
      esc(FRCUR)+'</b><span class="muted">'+ht(d.reply.ts)+
      (d.reply.by?(' · 火种 '+esc(d.reply.by)):'')+'</span></div>'+
      '<div class="b" style="width:max-content;max-width:min(100%,42em);white-space:pre-wrap;'+
      'word-break:break-word;text-align:left;min-width:2em">'+esc(d.reply.text)+'</div></div></div>';
    box2.insertAdjacentHTML('beforeend',one);
    const sig=(box2.dataset.sigs||'');
    const mySig='user|'+String(t).length+'|'+String(t).slice(0,16);
    const hisSig='friend|'+String(d.reply.text).length+'|'+String(d.reply.text).slice(0,16);
    box2.dataset.sigs=(sig?sig+'\u0001':'')+mySig+'\u0001'+hisSig;
    stickBottom(box2);
  }
}
// 轻量同步：只拉当前好友的消息，patch 进消息区
async function frSyncMessages(){
  if(!FRCUR)return;
  const d=await J('/api/friends/'+encodeURIComponent(FRCUR));
  if(!d.ok)return;
  const hs=d.history||[];FRHIST=hs;
  const f=d.friend||{};
  const frOneHtml2=function(m){
    const me=(m.from==='user');
    const tag=(!me&&m.why&&m.why!=='回你')?' <span class="tag">他主动找你</span>':'';
    const head=me?avImg('你','#3d5afe',34):avImg(f.name||FRCUR,f.color,34);
    return '<div class="msg '+(me?'me':'')+'">'+head+'<div><div class="meta">'+
      '<b>'+esc(me?'你':(f.name||FRCUR))+'</b>'+tag+
      '<span class="muted">'+ht(m.ts)+(m.by?(' · 火种 '+esc(m.by)):'')+'</span></div>'+
      '<div class="b" style="width:max-content;max-width:min(100%,42em);white-space:pre-wrap;'+
      'word-break:break-word;text-align:left;min-width:2em">'+esc(m.text)+'</div></div></div>';
  }; const _fhtml=hs.length?hs.map(frOneHtml2).join(''):'<div class="muted">还没聊过。他可能会自己先开口，你也可以先说。</div>';
  patchMessages(document.getElementById('fr_msgs'),hs,_fhtml,frOneHtml2);
}
document.getElementById('fr_send').onclick=frSay;
document.getElementById('fr_say').addEventListener('keydown',function(e){
  if(e.key==='Enter'){e.preventDefault();frSay()}});
document.getElementById('fr_new').onclick=function(){
  frShow('set');
  document.getElementById('fr_dname').value='';
  document.getElementById('fr_drel').value='';
  document.getElementById('fr_dmodel').value='';
  document.getElementById('fr_dpersona').value='';
};
document.getElementById('fr_save').onclick=async function(){
  const nm=(document.getElementById('fr_dname').value||'').trim();
  if(!nm){frToast('先给他起个名字');return}
  const d=await P('/api/personas',{name:nm,
    persona:document.getElementById('fr_dpersona').value,
    relation:document.getElementById('fr_drel').value,
    model:document.getElementById('fr_dmodel').value});
  frToast(d.ok?'已保存，他现在是你的好友了':(d.error||'失败'),!!d.ok);
  if(d.ok){FRCUR=nm;await frLoadList();frOpen(nm);frShow('chat')}
};
document.getElementById('fr_avatar_btn').onclick=function(){
  document.getElementById('fr_avatar_file').click()};
document.getElementById('fr_avatar_file').onchange=function(){
  const f=this.files&&this.files[0];if(!f)return;
  const nm=(document.getElementById('fr_dname').value||FRCUR||'').trim();
  if(!nm){frToast('先在名字里填好他的名字');return}
  const rd=new FileReader();
  rd.onload=async function(){
    const d=await P('/api/personas/avatar',{name:nm,data:rd.result});
    frToast(d.ok?'头像已换':(d.error||'失败'),!!d.ok);
    if(d.ok){await frLoadList();frOpen(nm)}};
  rd.readAsDataURL(f);this.value='';};
frLoadList();
setInterval(function(){
  frLoadList();
  if(FRCUR){  // 当前好友：静默同步消息（没变化就完全不重绘）
    frSyncMessages();
  }
},5000);
"""
    return body, js


def social_hub_html(tab="moments", embed=False):
    """一个页面装下社交模块：顶部页签切换，样式统一（不再一个模块一页）。"""
    _fb, _fj = _friends_inner()
    _gb, _gj = _groups_inner()
    body = """
<div class="row" style="align-items:center">
  <h1 style="margin:0">🌤️ 社交</h1>
  <div class="tabs" style="margin-left:14px">
    <button class="tab" data-tab="friends">好友</button>
    <button class="tab" data-tab="groups">群组</button>
  </div>
  <span class="grow"></span>
  <a href="/">← 回到单聊</a>
</div>
<div class="sub">定义一个人，他就是你的好友：有自己的朋友圈、会跟你聊天，也会**自己找你**说话。</div>

<div id="tab-friends" class="tabpane">__FRIENDS__</div>
<div id="tab-groups" class="tabpane">__GROUPS__</div>
""".replace("__FRIENDS__", _fb).replace("__GROUPS__", _gb)

    js = _fj + "\n" + _gj + """
function showTab(t){
  document.querySelectorAll('.tabpane').forEach(function(el){
    el.style.display=(el.id==='tab-'+t)?'block':'none'});
  document.querySelectorAll('.tab').forEach(function(b){
    b.classList.toggle('on',b.dataset.tab===t)});
  try{history.replaceState(null,'','/social?tab='+t)}catch(e){}
}
document.querySelectorAll('.tab').forEach(function(b){
  b.onclick=function(){showTab(b.dataset.tab)}});
(function(){
  const q=new URLSearchParams(location.search).get('tab')||'%s';
  if(q==='moments'){try{showTab('friends')}catch(e){}}
  showTab(q);
  const gid=new URLSearchParams(location.search).get('gid');
  if(gid&&typeof openGroup==='function'){setTimeout(function(){openGroup(gid)},300)}
})();
""" % (tab or "moments")
    page = _page("社交", body, js)
    if embed:
        # 被主界面用 iframe 嵌进来时：去掉外层留白，内容铺满容器（尺寸就不会"不对"了）
        page = page.replace("<style>", "<style>\n.wrap{max-width:none;padding:8px 10px 12px}\n"
                            ".im{flex:1 1 auto;min-height:0}\n", 1)
    return page


# ==================== 兼容旧链接：/aigroups/<gid> 直接跳到新页面 ====================
def group_room_html(gid):
    """老链接 `/aigroups/<gid>` 仍然可用：跳到新的一体页并选中这个群。"""
    body = """
<div class="card"><b>正在打开群聊…</b>
  <div class="muted" style="margin-top:8px">没自动跳转的话，点这里：<a id="lk" href="/aigroups">/aigroups</a></div>
</div>
<script>location.replace('/aigroups?gid=' + encodeURIComponent('%s'));
</script>""" % str(gid)
    return _page("群", body, "")
