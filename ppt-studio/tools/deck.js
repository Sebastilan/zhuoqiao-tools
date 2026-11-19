/* 讲座 HTML 演示引擎。键:→/↓/空格/回车/PgDn/点击/左滑=下一步;←/↑/PgUp/右键/右滑=上一页(整页显示);Home/End;
   N=备注;F 或 F5=全屏(翻页笔「放映」键);P=演讲者视图(新窗口同步);数字+回车=跳页;B 或 .=黑屏。全离线,不取任何外部资源。
   缩放:永远把 1920×1080 整页等比缩进可用区域、居中、留边不裁——独立打开时可用区域=视口;
   被别的页面嵌入(body 没有 .deck,如嵌进别的页面)时=所在容器宽 × 可见高度,且不碰宿主的地址栏、点击与输入框。 */
(function(){
  const deck=document.getElementById('deck');
  const stage=document.getElementById('stage');
  const slides=[...stage.querySelectorAll(':scope>.slide')];
  const standalone=document.body.classList.contains('deck');
  const q=new URLSearchParams(location.search);
  const isPresenter=standalone&&q.has('presenter'), isThumb=standalone&&q.has('thumb');
  let cur=0, step=0, jumpBuf='';
  const $=id=>document.getElementById(id);
  const steps=s=>Math.max(0,...[...s.querySelectorAll('[data-s]')].map(e=>+e.dataset.s||0));
  function fit(){
    let W, H;
    if(standalone){ W=deck.clientWidth; H=deck.clientHeight; }
    else{
      W=deck.clientWidth;
      const vh=(window.visualViewport?window.visualViewport.height:innerHeight);
      const top=deck.getBoundingClientRect().top+(window.scrollY||0);   // 画布顶端在文档里的位置(宿主顶栏之下)
      H=Math.min(W*9/16, Math.max(160, vh-top-8));
      deck.style.height=Math.round(H)+'px';
    }
    if(!W||!H) return;
    const k=Math.min(W/1920,H/1080);
    stage.style.transform=`translate(${(W-1920*k)/2}px,${(H-1080*k)/2}px) scale(${k})`;
  }
  // 自适应缩字:[data-fit="底线y"] 的元素进页后若超出底线(画布坐标),逐级缩字号直到放下——防不同机器字体度量差异把结尾裁掉
  function fitText(s){
    const sr=s.getBoundingClientRect(); if(!sr.height) return; const k=sr.height/1080;
    s.querySelectorAll('[data-fit]').forEach(el=>{
      const lim=+el.dataset.fit||1040; if(!el.dataset.fs0) el.dataset.fs0=parseFloat(getComputedStyle(el).fontSize);
      let fs=+el.dataset.fs0; el.style.fontSize=fs+'px';
      for(let i=0;i<16;i++){ const b=(el.getBoundingClientRect().bottom-sr.top)/k; if(b<=lim) break; fs-=1; el.style.fontSize=fs+'px'; }
    });
  }
  function setHash(){ if(standalone&&!isThumb) history.replaceState(null,'','#'+(cur+1)+(step?'.'+step:'')); }
  function applyStep(s,n){s.querySelectorAll('[data-s]').forEach(e=>e.classList.toggle('shown',(+e.dataset.s)<=n)); s.dataset.at=n;}
  function show(i,n,silent){
    i=Math.max(0,Math.min(slides.length-1,i));
    const s=slides[i];
    if(i!==cur||!s.classList.contains('on')){slides.forEach(x=>{x.classList.remove('on');x.querySelectorAll('video').forEach(v=>{try{v.pause()}catch(e){}});});
      void s.offsetWidth; s.classList.add('on');}
    cur=i; step=(n==='all')?steps(s):(n||0); applyStep(s,step); fitText(s);
    if($('pg')) $('pg').textContent=(i+1)+' / '+slides.length;
    const nt=s.querySelector('aside.notes');
    if($('notes')) $('notes').innerHTML=(s.dataset.title?'<b>'+s.dataset.title+'</b>\n':'')+(nt?nt.innerHTML.trim():'(本页无备注)');
    setHash(); if(!silent) sync();
  }
  function next(){const s=slides[cur]; if(step<steps(s)){step++;applyStep(s,step);setHash();sync();} else if(cur<slides.length-1) show(cur+1,0);}
  function prev(){ if(cur>0) show(cur-1,'all'); else show(0,0); }
  // 同步(演讲者视图):BroadcastChannel,退而用 localStorage
  let bc=null; try{ if(standalone) bc=new BroadcastChannel('deck-'+document.title);}catch(e){}
  function sync(){ if(!standalone) return; const m={cur,step,t:Date.now()}; if(bc) bc.postMessage(m); try{localStorage.setItem('deck-'+document.title,JSON.stringify(m));}catch(e){}}
  function recv(m){ if(!m) return; if(isPresenter) renderPresenter(m.cur,m.step); else if(m.from==='p'){show(m.cur,m.step,true);} }
  if(bc) bc.onmessage=e=>recv(e.data);
  if(standalone) addEventListener('storage',e=>{ if(e.key==='deck-'+document.title&&!bc) recv(JSON.parse(e.newValue)); });
  // 键盘:输入框里打字不翻页;带 Ctrl/Alt/Meta 的组合键不管
  // 全屏:标准接口优先,Safari 旧版走 webkit 前缀(旧接口不返回 Promise)
  const fsEl=()=>document.fullscreenElement||document.webkitFullscreenElement;
  const fsReq=el=>{try{const r=(el.requestFullscreen||el.webkitRequestFullscreen).call(el); if(r&&r.catch) r.catch(()=>{});}catch(e){}};
  const fsExit=()=>{try{const r=(document.exitFullscreen||document.webkitExitFullscreen).call(document); if(r&&r.catch) r.catch(()=>{});}catch(e){}};
  addEventListener('keydown',e=>{
    if(isPresenter) return;
    const t=e.target; if(t&&(t.isContentEditable||/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return;
    if(e.ctrlKey||e.altKey||e.metaKey) return;
    const k=e.key;
    if(/^[0-9]$/.test(k)){jumpBuf+=k;const j=$('jump');if(j){j.textContent=jumpBuf;j.style.display='block';}return;}
    if(k==='Enter'&&jumpBuf){show(+jumpBuf-1,0);jumpBuf='';if($('jump'))$('jump').style.display='none';return;}
    if(k==='Escape'){jumpBuf='';if($('jump'))$('jump').style.display='none';}
    if(['ArrowRight',' ','PageDown','Enter','ArrowDown'].includes(k)){e.preventDefault();next();}
    else if(['ArrowLeft','PageUp','ArrowUp','Backspace'].includes(k)){e.preventDefault();prev();}
    else if(k==='Home') show(0,0); else if(k==='End') show(slides.length-1,'all');
    else if(k==='n'||k==='N'){ if($('notes')) $('notes').classList.toggle('open'); }
    else if(k==='f'||k==='F'){ const el=standalone?document.documentElement:deck; if(!fsEl()) fsReq(el); else fsExit(); }
    else if(k==='F5'){e.preventDefault(); const el=standalone?document.documentElement:deck; if(!fsEl()) fsReq(el);}
    else if((k==='p'||k==='P')&&standalone) window.open(location.pathname+'?presenter#'+(cur+1),'presenter','width=1400,height=900');
    else if(k==='b'||k==='B'||k==='.'){stage.style.visibility=stage.style.visibility==='hidden'?'':'hidden';}
  });
  // 点击/右键/滑动只认画布内
  let swipeAt=0, tx=0, ty=0;
  deck.addEventListener('touchstart',e=>{const p=e.changedTouches[0];tx=p.clientX;ty=p.clientY;},{passive:true});
  deck.addEventListener('touchend',e=>{const p=e.changedTouches[0];const dx=p.clientX-tx,dy=p.clientY-ty;
    if(Math.abs(dx)>40&&Math.abs(dx)>Math.abs(dy)*1.2){swipeAt=Date.now(); if(dx<0) next(); else prev();}},{passive:true});
  deck.addEventListener('click',e=>{ if(isPresenter||isThumb) return; if(Date.now()-swipeAt<400) return; if(e.target.closest('a,button,video')) return; if(e.button===0) next(); });
  deck.addEventListener('contextmenu',e=>{e.preventDefault();prev();});
  if(standalone){ let ht; addEventListener('mousemove',()=>{document.body.classList.remove('hidecursor');clearTimeout(ht);ht=setTimeout(()=>document.body.classList.add('hidecursor'),2000);}); }
  addEventListener('resize',fit);
  if(window.visualViewport) visualViewport.addEventListener('resize',fit);
  if(window.ResizeObserver) new ResizeObserver(fit).observe(standalone?deck:deck.parentElement||deck);
  document.addEventListener('fullscreenchange',()=>setTimeout(fit,50)); document.addEventListener('webkitfullscreenchange',()=>setTimeout(fit,50));
  // 演讲者视图
  function renderPresenter(i,n){
    const pv=$('pv'); const base=location.pathname+'?thumb';
    const fr=(cls,ii,nn)=>{let box=pv.querySelector('.'+cls); let f=box.querySelector('iframe');
      if(!f){f=document.createElement('iframe');box.appendChild(f);}
      const src=base+'#'+(ii+1)+(nn==='all'?'.99':'.'+nn); if(f.dataset.src!==src){f.dataset.src=src;f.src=src;}
      const k=box.clientWidth/1920; f.style.transform=`scale(${k})`;};
    fr('now',i,n); fr('next',Math.min(i+1,slides.length-1),0);
    const s=slides[i]; const nt=s.querySelector('aside.notes');
    pv.querySelector('.txt').innerHTML=nt?nt.innerHTML.trim():'';
    pv.querySelector('.idx').textContent=`第 ${i+1} / ${slides.length} 页 · 第 ${n} / ${steps(s)} 步`;
  }
  if(isPresenter){
    document.body.classList.add('presenter');
    const t0=Date.now(); setInterval(()=>{const s=Math.floor((Date.now()-t0)/1000);
      document.querySelector('#pv .clock').textContent=String(Math.floor(s/60)).padStart(2,'0')+':'+String(s%60).padStart(2,'0');},1000);
    const h=(location.hash.slice(1)||'1').split('.'); cur=(+h[0]||1)-1; renderPresenter(cur,0);
    const send=(i,n)=>{const m={cur:i,step:n,from:'p'}; if(bc) bc.postMessage(m); renderPresenter(i,n);};
    window.onkeydown=e=>{const s=slides[cur];let n=+(document.querySelector('#pv .idx').textContent.match(/第 (\d+) \/ \d+ 步/)||[0,0])[1];
      if(['ArrowRight',' ','PageDown'].includes(e.key)){ if(n<steps(s)) n++; else if(cur<slides.length-1){cur++;n=0;} send(cur,n);}
      if(['ArrowLeft','PageUp'].includes(e.key)){ if(cur>0){cur--;n=steps(slides[cur]);} send(cur,n);} };
    return;
  }
  fit(); requestAnimationFrame(fit); setTimeout(fit,300);
  if(document.fonts&&document.fonts.ready) document.fonts.ready.then(()=>fitText(slides[cur]));
  addEventListener('resize',()=>setTimeout(()=>fitText(slides[cur]),60));
  const h=standalone?(location.hash.slice(1)||'1').split('.'):['1'];
  show((+h[0]||1)-1, h[1]?(+h[1]>=99?'all':+h[1]):0, true);
  if(isThumb){if($('pg'))$('pg').style.display='none'; addEventListener('hashchange',()=>{const h=location.hash.slice(1).split('.');show(+h[0]-1,+h[1]>=99?'all':+h[1]||0,true);});}
  // 右下角「全屏」按钮(独立放映才有;进全屏自动隐藏,Esc 退出;Mac 上 Ctrl+Cmd+F 是窗口全屏、留地址栏,点它或按 F 才是页面全屏)
  if(standalone&&!isThumb&&!isPresenter){
    const fb=document.createElement('button'); fb.id='fsb'; fb.type='button'; fb.textContent='⛶ 全屏'; fb.title='全屏放映(F),Esc 退出';
    fb.addEventListener('click',e=>{e.stopPropagation(); fsReq(document.documentElement); fb.blur();});
    const upd=()=>{fb.style.display=fsEl()?'none':'';}; document.addEventListener('fullscreenchange',upd); document.addEventListener('webkitfullscreenchange',upd);
    document.body.appendChild(fb); upd();
  }
  // 演讲计时(独立放映才有;嵌入别页、缩略、演讲者视图、打印/PDF 不带):视口最边缘半透明小字,时钟 + 已讲/倒计时
  // T 开始/暂停 · Shift+T 清零 · H 隐藏/显示 · Shift+H 或点时间条:正计时 ⇄ 一小时倒计时;刷新即清零(不记上次)
  if(standalone&&!isThumb&&!isPresenter){
    // 节奏(追加125):拼装时按 节奏.json 注入每张应到秒数 at[] 与总时长;没有就退回只计时
    const PACE=(()=>{try{return JSON.parse(document.getElementById('deck-pace').textContent);}catch(e){return null;}})();
    const LIM=PACE?PACE.total:3600;
    let S={acc:0,t0:0,run:false,down:false,hide:false,used:false};
    const save=()=>{};
    const tm=document.createElement('div'); tm.id='tm'; tm.title='T 开始/暂停 · Shift+T 清零 · H 隐藏 · 点这里切换正计时/倒计时'; document.body.appendChild(tm);
    const p2=n=>String(n).padStart(2,'0'), fmt=s=>(s>=3600?Math.floor(s/3600)+':':'')+p2(Math.floor(s%3600/60))+':'+p2(s%60);
    const el=()=>Math.floor((S.acc+(S.run?Date.now()-S.t0:0))/1000);
    function draw(){ const d=new Date(), e=el(); tm.style.display=S.hide?'none':'';
      let r; if(S.down){const left=LIM-e; r=left>=0?'剩 '+fmt(left):'超 '+fmt(-left); tm.classList.toggle('over',left<0); tm.classList.toggle('warn',left>=0&&left<300);} else {r='已讲 '+fmt(e)+(PACE?' / '+fmt(LIM):''); tm.classList.remove('over','warn');}
      let pv=''; if(PACE&&PACE.at[cur]!=null){ const a=PACE.at[cur], dv=e-a; pv='  ·  本页应到 '+fmt(a);
        if(S.used) pv+='  ·  偏差 '+(dv>0?'<b class="slow">+'+fmt(dv)+'</b>':dv<0?'<b class="fast">−'+fmt(-dv)+'</b>':'±00:00'); }
      tm.innerHTML=p2(d.getHours())+':'+p2(d.getMinutes())+'  ·  '+r+pv+(S.run?'':(S.used?'  ‖':'  · 按 T 开始')); }
    const toggleMode=()=>{S.down=!S.down;save();draw();};
    tm.addEventListener('click',e=>{e.stopPropagation();toggleMode();});
    addEventListener('keydown',e=>{ const t=e.target; if(t&&(t.isContentEditable||/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return; if(e.ctrlKey||e.altKey||e.metaKey) return;
      const k=e.key.toLowerCase();
      if(k==='t'){ if(e.shiftKey){S={...S,acc:0,t0:0,run:false,used:false};} else if(S.run){S.acc+=Date.now()-S.t0;S.run=false;} else {S.t0=Date.now();S.run=true;S.used=true;} save(); draw(); }
      else if(k==='h'){ if(e.shiftKey) toggleMode(); else {S.hide=!S.hide;save();draw();} } });
    draw(); setInterval(draw,500);
  }
})();
