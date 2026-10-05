import{A as e,E as t,F as n,H as r,U as i,W as a,X as o,at as s,et as c,n as l,rt as u,tt as d}from"./index-BmDne9UX.js";import{n as f,t as p}from"./_plugin-vue_export-helper-BNiQv4q3.js";import{r as m}from"./downloadTextFile-Cnv7UtiF.js";var h=250,g=8e3;function _(e,t){if(!Number.isInteger(t)||t<=0)throw RangeError(`${e} must be a positive integer`)}function v(e){if(typeof e.url!=`string`||e.url.length===0)throw TypeError(`url must be a non-empty string`);_(`capacity`,e.capacity),_(`channelCount`,e.channelCount);let t=e.reconnectBaseMs??h,n=e.reconnectMaxMs??g;if(!Number.isFinite(t)||!Number.isFinite(n)||t<=0||n<t)throw RangeError(`reconnect delay bounds are invalid`)}var y=class{options;worker;createWebSocket;reconnectBaseMs;reconnectMaxMs;serializeWorkerFrames;socket=null;reconnectTimer=null;reconnectAttempt=0;shouldRun=!1;disposed=!1;awaitingReadyFrame=!1;connectionGeneration=0;currentGeneration=0;nextFrameTicket=0;pendingReadyTickets=new Set;workerFrameQueue=[];workerFrameInFlight=null;constructor(e){v(e),this.options=e,this.worker=e.worker??e.createWorker?.()??new Worker(new URL(``+new URL(`streamDecoder.worker-D_FO9AVh.js`,import.meta.url).href,``+import.meta.url),{type:`module`}),this.createWebSocket=e.createWebSocket??(e=>new WebSocket(e)),this.reconnectBaseMs=e.reconnectBaseMs??h,this.reconnectMaxMs=e.reconnectMaxMs??g,this.serializeWorkerFrames=e.serializeWorkerFrames===!0,this.worker.onmessage=t=>{let n=t.data;if(n.type===`telemetry`){let e=n.acceptedConnectionGeneration===this.currentGeneration&&n.acceptedFrameTicket!==null&&this.pendingReadyTickets.delete(n.acceptedFrameTicket);this.awaitingReadyFrame&&e&&(this.reconnectAttempt=0,this.awaitingReadyFrame=!1,this.pendingReadyTickets.clear()),this.serializeWorkerFrames&&n.acceptedFrameTicket===this.workerFrameInFlight&&(this.workerFrameInFlight=null,this.flushWorkerFrame())}else n.type===`error`&&n.connectionGeneration===this.currentGeneration&&n.frameTicket!==void 0&&(this.pendingReadyTickets.delete(n.frameTicket),this.serializeWorkerFrames&&n.frameTicket===this.workerFrameInFlight&&(this.workerFrameInFlight=null,this.flushWorkerFrame()));e.onWorkerMessage?.(n)},this.worker.postMessage({type:`configure`,capacity:e.capacity,channelCount:e.channelCount,decoderMode:e.decoderMode,waveformSummaryOnly:e.waveformSummaryOnly})}start(){if(this.disposed)throw Error(`stream client is disposed`);this.shouldRun||(this.shouldRun=!0,this.reconnectAttempt=0,this.connect())}stop(){if(this.disposed)return;this.shouldRun=!1,this.awaitingReadyFrame=!1,this.currentGeneration=0,this.pendingReadyTickets.clear(),this.clearWorkerFrames(),this.clearReconnectTimer();let e=this.socket;this.socket=null,e&&(this.detach(e),e.close()),this.emitState({phase:`stopped`})}selectSerialPort(e){this.disposed||this.worker.postMessage({type:`serial-port`,port:e})}reset(){this.disposed||this.worker.postMessage({type:`reset`})}configure(e,t){this.disposed||(_(`capacity`,e),_(`channelCount`,t),this.worker.postMessage({type:`configure`,capacity:e,channelCount:t,decoderMode:this.options.decoderMode,waveformSummaryOnly:this.options.waveformSummaryOnly}))}resizeWaveform(e,t){this.disposed||(_(`capacity`,e),this.worker.postMessage({type:`waveform-capacity`,capacity:e,requestId:t}))}requestVisibleRange(e,t,n,r){this.disposed||this.worker.postMessage({type:`visible-range`,requestId:e,start:t,end:n,pixelWidth:r})}setWaveformDetail(e){this.disposed||this.worker.postMessage({type:`waveform-detail`,enabled:e})}requestHistorySnapshot(e){this.disposed||this.worker.postMessage({type:`history-snapshot`,requestId:e})}dispose(){this.disposed||(this.stop(),this.disposed=!0,this.worker.onmessage=null,this.worker.terminate())}connect(){if(!this.shouldRun||this.disposed)return;this.emitState({phase:this.reconnectAttempt===0?`connecting`:`reconnecting`});let e;try{e=this.createWebSocket(this.options.url)}catch(e){this.emitState({phase:`error`,error:e instanceof Error?e.message:String(e)}),this.shouldRun&&this.scheduleReconnect();return}let t=++this.connectionGeneration;this.currentGeneration=t,this.nextFrameTicket=0,this.pendingReadyTickets.clear(),this.clearWorkerFrames(),this.socket=e,e.binaryType=`arraybuffer`,e.onopen=()=>{e!==this.socket||!this.shouldRun||(this.awaitingReadyFrame=!0,this.options.token&&e.send(JSON.stringify({params:{token:this.options.token}})),this.emitState({phase:`connected`}))},e.onmessage=n=>{if(e!==this.socket||!this.shouldRun)return;if(!(n.data instanceof ArrayBuffer)){this.emitState({phase:`error`,error:`binary stream returned a non-ArrayBuffer message`});return}let r=n.data,i=++this.nextFrameTicket;this.pendingReadyTickets.add(i);let a={buffer:r,connectionGeneration:t,frameTicket:i};this.serializeWorkerFrames?(this.workerFrameQueue.push(a),this.flushWorkerFrame()):this.worker.postMessage({type:`frame`,...a},[r])},e.onerror=()=>{e===this.socket&&this.shouldRun&&this.emitState({phase:`error`,error:`binary stream WebSocket error`})},e.onclose=()=>{e===this.socket&&(this.socket=null,this.awaitingReadyFrame=!1,this.pendingReadyTickets.clear(),this.clearWorkerFrames(),this.shouldRun&&this.scheduleReconnect())}}scheduleReconnect(){this.clearReconnectTimer();let e=Math.min(this.reconnectMaxMs,this.reconnectBaseMs*2**this.reconnectAttempt);this.reconnectAttempt+=1,this.emitState({phase:`reconnecting`,reconnectDelayMs:e}),this.reconnectTimer=setTimeout(()=>{this.reconnectTimer=null,this.connect()},e)}clearReconnectTimer(){this.reconnectTimer!==null&&(clearTimeout(this.reconnectTimer),this.reconnectTimer=null)}detach(e){e.onopen=null,e.onmessage=null,e.onerror=null,e.onclose=null}flushWorkerFrame(){if(!this.serializeWorkerFrames||this.workerFrameInFlight!==null)return;let e=this.workerFrameQueue.shift();e&&(this.workerFrameInFlight=e.frameTicket,this.worker.postMessage({type:`frame`,...e},[e.buffer]))}clearWorkerFrames(){this.workerFrameQueue.length=0,this.workerFrameInFlight=null}emitState(e){this.options.onState?.(e)}};function b(e){if(l){let t=new URL(l,window.location.href);return t.protocol=t.protocol===`https:`?`wss:`:`ws:`,t.pathname=`${t.pathname.replace(/\/+$/,``)}/ws/streams/${e}`,t.search=``,t.hash=``,t.toString()}return`${window.location.protocol===`https:`?`wss:`:`ws:`}//${window.location.host}/ws/streams/${e}`}function x(e,n){let r=d({phase:`stopped`}),a=u(null),o=d(n.channelCount),s=u(null),l=u(null),f=u(null),p=u(null),m=u(null),h=u(null),g=u(null),_=u(null),v=u(null),x=u(null),S=d(null),C=n.capacity,w=0,T=null,E=null;function D(e){r.value=e,e.error&&(S.value=e.error)}let O=null,k=null,A=null;function j(){O!==null&&clearTimeout(O),O=null,k&&(p.value=k),A&&(a.value=A),k=null,A=null}function M(){O!==null&&clearTimeout(O),O=null,k=null,A=null}function N(){O===null&&(O=setTimeout(j,33))}function P(t){if(e===`superwatch`){if(t.type===`waveform-summary`){k={...t,collectedItemCount:t.collectedItemCount+(k?.collectedItemCount??0)},N();return}if(t.type===`telemetry`){A=t,N();return}(t.type===`channels`||t.type===`superwatch-metadata`)&&j()}switch(t.type){case`waveform-capacity-result`:{if(T?.id!==t.requestId)break;let e=T;if(T=null,C=t.capacity,t.error?e.reject(Error(t.error)):e.resolve(),E!==null){let e=E;E=null,H(e)}break}case`telemetry`:a.value=t;break;case`channels`:o.value=t.channelCount;break;case`render-envelope`:s.value=t;break;case`systemview-visible`:l.value=t;break;case`waveform-batch`:f.value=t;break;case`waveform-summary`:p.value=t;break;case`history-snapshot`:m.value=t;break;case`rtt-lines`:h.value=t;break;case`rtt-terminal`:g.value=t;break;case`superwatch-metadata`:_.value=t;break;case`serial-lines`:t.port===F&&(v.value=t);break;case`serial-terminal`:t.port===F&&(x.value=t);break;case`error`:S.value=t.message;break}}let F=``,I=(n.createClient??(e=>new y(e)))({url:b(e),token:n.token,capacity:n.capacity,channelCount:n.channelCount,decoderMode:n.decoderMode,serializeWorkerFrames:e===`systemview`,waveformSummaryOnly:e===`superwatch`,onState:D,onWorkerMessage:P});function L(e){F=e,v.value=null,x.value=null,I.selectSerialPort?.(e)}function R(){S.value=null,I.start()}function z(){j(),I.stop()}function B(){M(),a.value=null,s.value=null,l.value=null,f.value=null,p.value=null,m.value=null,h.value=null,g.value=null,_.value=null,v.value=null,x.value=null,S.value=null,I.reset()}function V(e){if(!Number.isInteger(e)||e<2||e>1e6)throw RangeError(`Invalid waveform capacity`);return T?Promise.reject(Error(`A capacity change is pending`)):I.resizeWaveform?new Promise((t,n)=>{let r=++w;T={id:r,resolve:t,reject:n};try{I.resizeWaveform(e,r)}catch(e){T=null,n(e)}}):Promise.reject(Error(`Capacity changes are unavailable`))}function H(e){if(T){E=e;return}M(),o.value=e,a.value=null,s.value=null,f.value=null,p.value=null,m.value=null,h.value=null,g.value=null,_.value=null,v.value=null,x.value=null,I.configure(C,e)}function U(e,t,n,r){I.requestVisibleRange(e,t,n,r)}function W(e){I.setWaveformDetail?.(e)}function G(e){I.requestHistorySnapshot?.(e)}return n.autoStart&&R(),i(()=>{T?.reject(Error(`Viewer closed`)),T=null,M(),I.dispose()}),{state:c(r),connected:t(()=>r.value.phase===`connected`),telemetry:c(a),channelCount:c(o),envelope:c(s),systemViewVisible:c(l),waveformBatch:c(f),waveformSummary:c(p),historySnapshot:c(m),rttLines:c(h),rttTerminal:c(g),superwatchMetadata:c(_),serialLines:c(v),serialTerminal:c(x),error:c(S),start:R,stop:z,reset:B,configure:H,resizeWaveform:V,selectSerialPort:L,requestVisibleRange:U,setWaveformDetail:W,requestHistorySnapshot:G}}var S=.5,C=2e3,w=class{currentRate=60;renderCostEwma=null;pendingUpshift=null;pendingUpshiftAt=0;reset(e=60){if(!Number.isFinite(e)||e<=0)throw RangeError(`initialRate must be a positive finite number`);this.currentRate=e,this.renderCostEwma=null,this.pendingUpshift=null,this.pendingUpshiftAt=0}observe(e){let t=Number.isFinite(e.renderCostMs)?Math.max(0,e.renderCostMs):0;this.renderCostEwma=this.renderCostEwma===null?t:this.renderCostEwma*.85+t*.15;let n=Number.isFinite(e.pixelWidth)&&e.pixelWidth>0?e.pixelWidth:1,r=(Number.isFinite(e.visibleItems)?Math.max(0,e.visibleItems):0)/n,i=this.desiredRate(r,this.renderCostEwma);return i<this.currentRate?(this.currentRate=i,this.pendingUpshift=null,this.currentRate):i===this.currentRate?(this.pendingUpshift=null,this.currentRate):this.pendingUpshift===i?(e.now-this.pendingUpshiftAt>=C&&(this.currentRate=i,this.pendingUpshift=null),this.currentRate):(this.pendingUpshift=i,this.pendingUpshiftAt=e.now,this.currentRate)}desiredRate(e,t){return this.currentRate===60?t>=10?20:e>=1||t>=5?30:60:this.currentRate===30?t>=10?20:e<=.65&&t<=4?60:30:t<=7?30:20}};function T(){return{now:()=>performance.now(),requestAnimationFrame:e=>requestAnimationFrame(e),cancelAnimationFrame:e=>cancelAnimationFrame(e),isDocumentHidden:()=>document.hidden,addVisibilityListener:e=>document.addEventListener(`visibilitychange`,e),removeVisibilityListener:e=>document.removeEventListener(`visibilitychange`,e)}}var E=class{render;dependencies;collectionTelemetry;frameIntervalMs;continuous;dirty=new Set;visibilityListener=()=>this.visibilityChanged();frameId=null;lastRender=-1/0;generation=0;running=!1;disposed=!1;constructor(e,t=T(),n=()=>{},r={}){this.render=e,this.dependencies=t,this.collectionTelemetry=n;let i=r.frameRate??30;if(!Number.isFinite(i)||i<=0)throw RangeError(`frameRate must be a positive finite number`);this.frameIntervalMs=1e3/i,this.continuous=r.continuous===!0,t.addVisibilityListener(this.visibilityListener)}start(){this.running||this.disposed||(this.running=!0,this.generation+=1,this.scheduleIfNeeded())}stop(){this.running&&(this.running=!1,this.generation+=1,this.frameId!==null&&(this.dependencies.cancelAnimationFrame(this.frameId),this.frameId=null))}dispose(){this.disposed||(this.stop(),this.disposed=!0,this.dirty.clear(),this.dependencies.removeVisibilityListener(this.visibilityListener))}invalidate(e){this.disposed||(this.dirty.add(e),this.scheduleIfNeeded())}setFrameRate(e){if(!Number.isFinite(e)||e<=0)throw RangeError(`frameRate must be a positive finite number`);this.frameIntervalMs=1e3/e}recordCollection(e){this.disposed||this.collectionTelemetry(e)}scheduleIfNeeded(){if(!this.running||this.disposed||this.frameId!==null||!this.continuous&&this.dirty.size===0||this.dependencies.isDocumentHidden())return;let e=this.generation;this.frameId=this.dependencies.requestAnimationFrame(()=>this.onFrame(e))}onFrame(e){if(e!==this.generation||!this.running||this.disposed||(this.frameId=null,this.dependencies.isDocumentHidden()))return;let t=this.dependencies.now();if(t-this.lastRender>=this.frameIntervalMs-S){let e=new Set(this.dirty);this.dirty.clear(),this.lastRender=t,this.render(e)}this.scheduleIfNeeded()}visibilityChanged(){this.dependencies.isDocumentHidden()||this.scheduleIfNeeded()}},D=``+new URL(`rtt_i18n-zYKyuFTH.js`,import.meta.url).href,O=``+new URL(`rtt_viewer-7zAwYFPO.js`,import.meta.url).href;function k(e,t={}){let n=t.language===`en`,r=(e,t)=>n?t:e,i=document.createElement(`button`);i.type=`button`,i.className=`panel-btn`,i.dataset.testid=`open-superwatch-replay`,i.textContent=r(`日志回放`,`Log replay`),e.append(i);let a=null;return i.onclick=()=>{if(a)return;let e=document.createElement(`dialog`);e.className=`sw-replay`,e.setAttribute(`aria-label`,r(`SuperWatch 离线日志回放`,`SuperWatch offline log replay`)),e.addEventListener(`keydown`,e=>e.stopPropagation()),e.innerHTML=`
      <div class="sw-replay-heading"><div><h2>SuperWatch · ${r(`日志回放`,`Log replay`)}</h2>
        <p>${r(`本地离线查看 · 不修改设备或实时采样`,`Local offline viewer · Device and live acquisition remain unchanged`)}</p></div>
        <button type="button" data-action="close">${r(`返回实时页面`,`Return to live view`)}</button></div>
      <div class="sw-replay-import"><label>${r(`导入日志`,`Import log`)}
        <input data-testid="replay-file" type="file" accept=".csv,.txt,.log,.jsonl,.ndjson"></label>
        <button type="button" data-action="cancel" hidden>${r(`取消加载`,`Cancel loading`)}</button>
        <span>${r(`CSV / TXT / JSONL · 最大 256 MiB、64 通道、800 万数值`,`CSV / TXT / JSONL · Up to 256 MiB, 64 channels, 8M values`)}</span></div>
      <div class="sw-replay-message" role="status" aria-live="polite">${r(`请选择 SuperWatch 导出的带时间戳日志。无需连接设备。`,`Select a timestamped SuperWatch log. No device connection is required.`)}</div>
      <progress class="sw-replay-progress" max="1" value="0" hidden></progress>
      <div class="sw-replay-controls">
        <button type="button" data-action="play" disabled>${r(`播放`,`Play`)}</button>
        <button type="button" data-action="restart" disabled>${r(`重新播放`,`Restart`)}</button>
        <label>${r(`速度`,`Speed`)} <select data-action="speed" disabled><option>0.25</option><option>0.5</option><option selected>1</option><option>2</option><option>4</option><option>8</option><option>16</option></select> ×</label>
        <label>${r(`时间窗口`,`Window`)} <select data-action="span" disabled><option value="2">2 s</option><option value="10" selected>10 s</option><option value="60">60 s</option><option value="all">${r(`全部`,`All`)}</option></select></label>
        <button type="button" data-action="overview" disabled>${r(`查看全部`,`Show all`)}</button>
        <output data-testid="replay-time">0.000 / 0.000 s</output>
        <span data-testid="replay-state">${r(`未加载`,`No file`)}</span>
      </div>
      <input class="sw-replay-seek" data-testid="replay-seek" type="range" min="0" max="1" step="any" value="0" disabled aria-label="${r(`回放时间轴（秒）`,`Replay timeline (seconds)`)}">
      <div class="sw-replay-content"><aside><div class="sw-replay-channel-heading">${r(`通道（同时显示最多 16 路）`,`Channels (up to 16 visible)`)}</div><div class="sw-replay-channels"></div></aside>
        <div class="sw-replay-chart-wrap"><canvas aria-label="${r(`日志回放波形`,`Log replay waveforms`)}" role="img"></canvas><p class="sw-replay-chart-hint">${r(`拖动时间轴定位；滚轮缩放时间窗口。各通道纵轴独立。`,`Seek with the timeline; scroll to zoom time. Each channel has its own Y scale.`)}</p></div></div>`,document.body.append(e);let t=t=>e.querySelector(t),n=e=>t(`[data-action="${e}"]`),o=t(`.sw-replay-message`),s=t(`.sw-replay-progress`),c=t(`[data-testid=replay-file]`),l=t(`[data-testid=replay-seek]`),u=t(`[data-testid=replay-time]`),d=t(`[data-testid=replay-state]`),f=t(`canvas`),p=t(`.sw-replay-chart-wrap`),m=f.getContext(`2d`),h=null,g=null,_=null,v=!1,y=!1,b=0,x=1,S=10,C=0,w=!1,T=!1,E=0,D=0,O=0,k=0,A=new Set,j=new Map,M=[`#68b7ff`,`#ffaf67`,`#73d6a1`,`#dc9bfa`,`#e6d779`,`#f58fa6`,`#79d7d7`,`#c9b9ff`];function N(e,t=!1){o.textContent=e,o.classList.toggle(`error`,t)}function P(e){for(let t of[`play`,`restart`,`speed`,`span`,`overview`])n(t).disabled=!e;l.disabled=!e}function F(){u.textContent=`${b.toFixed(3)} / ${(g?.duration||0).toFixed(3)} s`,l.value=String(b),d.textContent=g?y?r(`播放中`,`Playing`):b>=g.duration?r(`回放结束`,`Ended`):r(`已暂停`,`Paused`):r(`未加载`,`No file`),e.dataset.playbackState=g?y?`playing`:b>=g.duration?`ended`:`paused`:`empty`,n(`play`).textContent=y?r(`暂停`,`Pause`):r(`播放`,`Play`)}function I(){if(!(!h||!g||v)){if(w){T=!0;return}w=!0,T=!1,h.postMessage({type:`view`,id:++C,position:b,span:S,width:Math.max(1,p.clientWidth-32),names:[...A]})}}function L(){let e=Math.max(240,p.clientWidth-24),t=Math.max(240,(_?.channels.length||1)*110+30),n=Math.min(2,window.devicePixelRatio||1);if(f.width=Math.floor(e*n),f.height=Math.floor(t*n),f.style.width=`${e}px`,f.style.height=`${t}px`,m.setTransform(n,0,0,n,0,0),m.fillStyle=`#0e151d`,m.fillRect(0,0,e,t),m.font=`12px monospace`,!_?.channels.length){m.fillStyle=`#aebccc`,m.fillText(r(`导入日志并选择通道`,`Import a log and select channels`),16,36);return}_.channels.forEach((t,n)=>{let r=n*110,i=e-75-12,a=M[n%M.length],o=1/0,s=-1/0;for(let[,e]of t.points)o=Math.min(o,e),s=Math.max(s,e);Number.isFinite(o)||(o=0,s=1),o===s&&(o-=Math.max(1,Math.abs(o)*.05),s+=Math.max(1,Math.abs(s)*.05)),m.save(),m.beginPath(),m.rect(0,r,e,110),m.clip(),m.fillStyle=a,m.fillText(t.name,10,r+15,e-20),m.fillStyle=`#96a8bb`,m.fillText(s.toPrecision(4),6,r+36),m.fillText(o.toPrecision(4),6,r+92),m.strokeStyle=`#2a3948`,m.beginPath(),m.moveTo(75,r+26),m.lineTo(75,r+94),m.lineTo(e-10,r+94),m.stroke(),m.strokeStyle=a,m.beginPath(),t.points.forEach(([e,n],a)=>{let c=75+(e-_.start)/(_.end-_.start)*i,l=r+90-(n-o)/(s-o)*60;a?m.lineTo(c,l):m.moveTo(c,l),t.points.length===1&&m.fillRect(c-2,l-2,4,4)}),m.stroke(),m.restore();let c=j.get(t.name)?.querySelector(`output`);c&&(c.textContent=t.latest===null?`—`:String(Number(t.latest.toPrecision(9))))}),m.fillStyle=`#aebccc`,m.fillText(_.start.toFixed(3)+` s`,75,t-8),m.textAlign=`right`,m.fillText(_.end.toFixed(3)+` s`,e-12,t-8),m.textAlign=`left`,f.dataset.points=String(_.channels.reduce((e,t)=>e+t.points.length,0)),f.dataset.position=String(_.position)}function R(e){if(!(!y||v)){if(b=Math.min(g.duration,O+(e-D)/1e3*x),(e-k>=33||b>=g.duration)&&(k=e,F(),I()),b>=g.duration){y=!1,F();return}E=requestAnimationFrame(R)}}function z(){y&&(b=Math.min(g.duration,O+(performance.now()-D)/1e3*x)),y=!1,cancelAnimationFrame(E),F(),I()}function B(){if(g){if(b>=g.duration&&(b=0),!g.duration){F(),I();return}y=!0,O=b,D=performance.now(),F(),cancelAnimationFrame(E),E=requestAnimationFrame(R)}}function V(){h?.terminate(),h=null,w=!1,T=!1}function H(){z(),V(),g=null,_=null,b=0,j.clear(),A.clear(),t(`.sw-replay-channels`).replaceChildren(),s.hidden=!0,n(`cancel`).hidden=!0,P(!1),F(),L()}function U(i){if(H(),!i)return;s.hidden=!1,s.value=0,n(`cancel`).hidden=!1,N(r(`正在加载：`,`Loading: `)+i.name);try{h=new Worker(new URL(``+new URL(`superwatch_replay_worker-D0VoV7Ue.js`,import.meta.url).href,``+import.meta.url),{type:`module`})}catch(e){H(),N(r(`无法启动日志解析：`,`Cannot start log parser: `)+e.message,!0);return}let a=h;a.onerror=()=>{h===a&&(H(),N(r(`日志解析线程失败，请重新导入。`,`Log worker failed. Please import again.`),!0))},a.onmessage=({data:c})=>{v||h!==a||(c.type===`progress`?s.value=c.fraction:c.type===`error`?(H(),N(r(`导入失败：`,`Import failed: `)+c.message,!0)):c.type===`loaded`?(g=c,s.hidden=!0,n(`cancel`).hidden=!0,e.dataset.logRows=String(c.rows),e.dataset.logValues=String(c.values),l.max=String(c.duration||1),b=0,S=10,n(`span`).value=`10`,P(!0),N(`${i.name} · ${c.rows.toLocaleString()} ${r(`行`,`rows`)} · ${c.channels.length} ${r(`通道`,`channels`)} · ${c.duration.toFixed(3)} s`),c.writeEvents&&(o.textContent+=` · ${c.writeEvents} ${r(`条写入记录（不计入采样）`,`write records (excluded from samples)`)}`),c.channels.forEach((e,n)=>{let i=document.createElement(`label`),a=document.createElement(`input`),o=document.createElement(`span`),s=document.createElement(`output`);a.type=`checkbox`,a.checked=n<8,a.checked&&A.add(e.name),o.textContent=e.name,o.title=e.name,s.textContent=`—`,a.onchange=()=>{if(a.checked&&A.size>=16){a.checked=!1,N(r(`最多同时显示 16 路；请先取消一个通道。`,`Select at most 16 visible channels; uncheck one first.`),!0);return}a.checked?A.add(e.name):A.delete(e.name),I()},i.append(a,o,s),j.set(e.name,i),t(`.sw-replay-channels`).append(i)}),F(),I()):c.type===`view`&&c.id===C&&(w=!1,_=c,L(),T&&I()))},a.postMessage({type:`load`,file:i})}c.onchange=()=>{let e=c.files?.[0];e&&U(e),c.value=``},n(`cancel`).onclick=()=>{H(),N(r(`已取消加载`,`Loading cancelled`))},n(`play`).onclick=()=>y?z():B(),n(`restart`).onclick=()=>{z(),b=0,B()},n(`speed`).onchange=()=>{let e=y;z(),x=Number(n(`speed`).value),e&&B()},n(`span`).onchange=()=>{S=n(`span`).value===`all`?Math.max(.001,g.duration):Number(n(`span`).value),I()},n(`overview`).onclick=()=>{z(),b=g.duration,S=Math.max(.001,g.duration),n(`span`).value=`all`,F(),I()},l.oninput=()=>{let e=Number(l.value);z(),b=e,F(),I()},f.addEventListener(`wheel`,e=>{!g||e.ctrlKey||(e.preventDefault(),S=Math.max(.001,Math.min(Math.max(.001,g.duration),S*(e.deltaY>0?1.25:.8))),n(`span`).value=``,I())},{passive:!1});let W=new ResizeObserver(()=>{L(),I()});W.observe(p),a=()=>{v=!0,cancelAnimationFrame(E),V(),W.disconnect(),e.close(),e.remove(),a=null,i.focus()},n(`close`).onclick=a,e.addEventListener(`cancel`,e=>{e.preventDefault(),a?.()}),e.showModal(),L()},()=>{a?.(),i.remove()}}var A=p(n({__name:`WaveformViewer`,props:{mode:{},deviceConnected:{type:Boolean},hiddenChannels:{},arraySnapshotPath:{}},emits:[`latest-values`],setup(t,{emit:n}){let c=t,u=n,p=d(),h=x(c.mode===`VOFA`?`vofa`:`superwatch`,{capacity:c.mode===`VOFA`?1e4:5e4,channelCount:1}),g=[],_=null,v=null,y=0,b=0,S=null,C=!1,w=!1,T=new Set,A=`stopped`,j=null,M=0,N=null,P=null,F=0,I=!1,L=null;function R(e=!1){if(S!==null){C=!0,w||=e;return}let t=(window.__waveformViewers?.[c.mode])?.getBinaryVisibleRange?.();if(!t)return;let{start:n,end:r,pixelWidth:i}=t;![n,r,i].every(Number.isFinite)||i<1||(C=!1,w=!1,S=++y,e&&T.add(S),h.requestVisibleRange(S,n,r,i))}function z(){y++,S=null,C=!1,w=!1,T.clear()}let B=new E(()=>R(!1));function V(e){e?.setBinaryCapacityRequester?.(e=>h.resizeWaveform(e)),!(c.mode!==`SuperWatch`||!e)&&(e.setBinaryHistoryRequester?.(()=>{h.requestHistorySnapshot?.(++b)}),e.setBinaryDetailRequester?.(e=>{h.setWaveformDetail?.(e)}),e.setBinaryVisibleRangeRequester?.(()=>R(!0)))}function H(e){return JSON.stringify(e.map((e,t)=>[e.name??e.addr??e.address??t,e.type??`float`,e.size??4,e.addr??e.address??null,e.unit??``]))}function U(e){if(I)return;let t=H(e);t!==_&&(_=t,g=e.map(e=>({...e})),z(),v=null,c.mode===`VOFA`&&h.configure(Math.max(1,e.length)),(window.__waveformViewers?.[c.mode])?.configureBinaryChannels?.(g),W())}function W(){let e=[...c.hiddenChannels??[]].sort();window.__waveformViewers?.[c.mode]?.setHiddenChannels?.(e)}function G(){F+=1,P!==null&&(clearTimeout(P),P=null)}async function K(e){if(!(I||c.mode!==`SuperWatch`||!c.arraySnapshotPath||!c.deviceConnected)){try{let e=await fetch(`${l}/api/dash/superwatch/array-snapshot`),t=await e.json().catch(()=>({}));e.ok&&t?.snapshot?.name===c.arraySnapshotPath?window.__waveformViewers?.SuperWatch?.setArraySnapshot?.(t.snapshot):window.__waveformViewers?.SuperWatch?.setArraySnapshot?.(null)}catch{}!I&&e===F&&c.arraySnapshotPath&&(P=setTimeout(()=>{P=null,K(e)},50))}}function q(){if(G(),c.mode!==`SuperWatch`||!c.arraySnapshotPath||!c.deviceConnected){window.__waveformViewers?.SuperWatch?.setArraySnapshot?.(null);return}K(F)}function J(e){let t=e.detail;Array.isArray(t)&&U(t)}function Y(){I||(z(),v=null,h.reset(),window.__waveformViewers?.[c.mode]?.resetBinaryStream?.())}function X(){M++,j!==null&&(clearTimeout(j),j=null)}async function Z(e,t){let n=null;try{let e=await fetch(`${l}/api/dash/${c.mode===`VOFA`?`vofa`:`superwatch`}/status`);n=e.ok?await e.json():null}catch{}if(!(I||e!==M)){if(n){if(N=n,t){let e=c.mode===`VOFA`?n.channels:n.items;U(Array.isArray(e)?e:[])}window.__waveformViewers?.[c.mode]?.updateAcquisitionStatus?.(n)}t&&h.start(),j=setTimeout(()=>{j=null,Z(e,!1)},1e3)}}function Q(e){I||(X(),Z(M,e))}function $(e){let t=e.detail;t===`running`?(h.stop(),Y(),h.start(),Q(!1)):t===`stopped`&&(v=null,h.stop(),X())}o(()=>h.waveformBatch.value,e=>{if(!e)return;if(v=e,c.mode===`SuperWatch`&&!h.waveformSummary&&e.itemCount>0&&e.channelCount===g.length){let t=new Float32Array(e.values),n=(e.itemCount-1)*e.channelCount,r={};for(let i=0;i<e.channelCount;i+=1){let e=String(g[i]?.name??``),a=t[n+i];e&&Number.isFinite(a)&&(r[e]=a)}u(`latest-values`,r)}let t=window.__waveformViewers?.[c.mode];t?.acceptBinaryBatch&&(t.acceptBinaryBatch(e,g),v=null),c.mode!==`SuperWatch`&&(B?.recordCollection(e.itemCount),B?.invalidate(`data`))}),o(()=>h.waveformSummary?.value,e=>{if(!e||c.mode!==`SuperWatch`)return;let t=new Float32Array(e.latestValues);if(e.channelCount===g.length&&t.length===e.channelCount){let n={};for(let r=0;r<e.channelCount;r+=1){let e=String(g[r]?.name??``);e&&Number.isFinite(t[r])&&(n[e]=t[r])}u(`latest-values`,n)}window.__waveformViewers?.SuperWatch?.acceptBinarySummary?.(e,g),B?.recordCollection(e.collectedItemCount),B?.invalidate(`data`)}),o(()=>h.historySnapshot?.value,e=>{!e||c.mode!==`SuperWatch`||window.__waveformViewers?.SuperWatch?.exportBinaryHistorySnapshot?.(e)}),o(()=>h.envelope.value,e=>{if(!e||e.requestId!==S)return;S=null;let t=T.delete(e.requestId);window.__waveformViewers?.[c.mode]?.renderBinaryEnvelope?.(e,t),C&&R(w)}),o(()=>h.superwatchMetadata.value,e=>{!e||c.mode!==`SuperWatch`||U(e.channels)}),o([()=>h.state.value,()=>h.telemetry.value,()=>h.error.value],([e,t,n])=>{e&&(e.phase===`reconnecting`&&A!==`reconnecting`&&Y(),A=e.phase,window.__waveformViewers?.[c.mode]?.updateBinaryHealth?.({phase:e.phase,reconnectDelayMs:e.reconnectDelayMs,bufferedSamples:t?.bufferedSamples??0,transportDroppedBatches:t?.transportDroppedBatches??0,backendDroppedBatches:t?.backendDroppedBatches??0,backendDroppedItems:t?.backendDroppedItems??0,error:e.phase===`connected`||e.phase===`stopped`?null:n}))}),r(()=>{if(!p.value)return;let e=p.value;window.__MKLINK_SAVE_FILE__=(e,t)=>m(e,t),e.innerHTML=ee(c.mode),c.mode===`SuperWatch`&&(L=k(e.querySelector(`.header-actions`),{language:f.value})),te(e,c.mode);{c.mode===`VOFA`&&window.addEventListener(`mklink:vofa-channels`,J),window.addEventListener(`mklink:vofa-stream-state`,$),B?.start(),Q(!0),q();let e=window.__waveformViewers?.[c.mode];V(e)}}),o(()=>c.deviceConnected,e=>{let t=window.__waveformViewers;t?.[c.mode]?.setDeviceConnected&&t[c.mode].setDeviceConnected(e)}),o(()=>c.hiddenChannels,W),o([()=>c.arraySnapshotPath,()=>c.deviceConnected],q),o(f,e=>{window.setLang?.(e)}),i(()=>{L?.(),I=!0,X(),G(),h.stop(),B?.dispose(),window.removeEventListener(`mklink:vofa-channels`,J),window.removeEventListener(`mklink:vofa-stream-state`,$);try{let e=window.__waveformViewers;e?.[c.mode]?.dispose?.(),e&&delete e[c.mode]}catch{}p.value&&(p.value.innerHTML=``),window.__MKLINK_SAVE_FILE__&&delete window.__MKLINK_SAVE_FILE__});function ee(e){return`
<header>
  <div class="header-status">
    <h1>MKLink ${e}</h1>
    <span id="mode-badge" class="badge badge-mode">${e}</span>
    <span id="conn-status" class="badge badge-ok" data-i18n="live">live</span>
    <span id="pts-count" class="badge badge-info">0 pts</span>
    <span id="sample-rate-badge" class="badge badge-info">-- Hz</span>
    <span id="transport-state-badge" class="badge badge-info">transport stopped</span>
    <span id="transport-health-badge" class="badge badge-info">transport 0 / backend 0/0 / buffer 0</span>
  </div>
  <div class="header-actions">
    <button id="btn-cursor-toggle" class="panel-btn" data-i18n-title="cursors_tip" data-i18n="cursors">Cursors</button>
    <button id="btn-cursor-mode" class="panel-btn" style="display:none;" data-i18n-title="cursor_mode_tip">Time</button>
    <button id="btn-save-project" class="panel-btn" data-i18n-title="save_project_tip" data-i18n="save">Save</button>
    <button id="btn-load-project" class="panel-btn" data-i18n-title="load_project_tip" data-i18n="load">Load</button>
    <button id="btn-thresholds" class="panel-btn" data-i18n-title="thresholds_tip" data-i18n="thresholds">Thresholds</button>
    <button id="btn-export-csv" class="panel-btn" data-i18n-title="export_csv_tip">CSV</button>
    <button id="btn-export-png" class="panel-btn" data-i18n-title="export_png_tip">PNG</button>
    <button id="btn-help" class="panel-btn" data-i18n-title="help_tip">?</button>
    <input id="project-load-input" class="hidden-file-input" type="file" accept="application/json,.json">
  </div>
</header>

<div id="control-toolbar">
  <button id="btn-start" class="ctrl-btn active" data-i18n="start">Start</button>
  <button id="btn-pause" class="ctrl-btn" data-i18n="pause">Pause</button>
  <button id="btn-stop" class="ctrl-btn danger" data-i18n="stop">Stop</button>
  <span id="collection-status-badge" class="status-running" data-i18n="running">Running</span>
  <div class="ctrl-sep"></div>
  <label data-i18n="buffer">Buffer</label>
  <input type="number" id="buffer-input" value="${e===`SuperWatch`?5e4:1e4}" min="${e===`SuperWatch`?5e4:2}" max="1000000" step="1">
  <span class="buffer-unit">pts/ch</span>
  <span id="buffer-memory-estimate" class="buffer-memory-estimate" data-i18n-title="buffer_memory_tip">~0 MB</span>
  <button id="btn-apply-buffer" class="ctrl-btn" data-i18n="apply">Apply</button>
  <div class="ctrl-sep"></div>
  <div id="interval-group">
    <label data-i18n="interval">Interval</label>
    <input type="number" id="interval-input" value="${e===`SuperWatch`?`0.001`:`0`}" step="${e===`SuperWatch`?`0.000001`:`0.001`}" min="${e===`SuperWatch`?`0.000001`:`0`}" max="60">
    <span class="interval-unit">s</span>
    <button id="btn-apply-interval" class="ctrl-btn" data-i18n="apply">Apply</button>
  </div>
</div>

<div id="trigger-toolbar">
  <button id="trigger-enable-btn" data-i18n="trigger">Trigger</button>
  <span id="trigger-state-badge" class="trigger-state-idle" data-i18n="idle">Idle</span>
  <div class="trigger-sep"></div>
  <label data-i18n="source">Source</label>
  <select id="trigger-source"><option value="">--</option></select>
  <div class="trigger-sep"></div>
  <label data-i18n="edge">Edge</label>
  <select id="trigger-edge">
    <option value="rising" data-i18n="rising">Rising</option>
    <option value="falling" data-i18n="falling">Falling</option>
    <option value="both" data-i18n="both">Both</option>
  </select>
  <div class="trigger-sep"></div>
  <label data-i18n="level">Level</label>
  <input type="number" id="trigger-level" value="0" step="0.1">
  <div class="trigger-sep"></div>
  <label data-i18n="mode">Mode</label>
  <select id="trigger-mode">
    <option value="auto" data-i18n="auto">Auto</option>
    <option value="normal" data-i18n="normal">Normal</option>
    <option value="single" data-i18n="single">Single</option>
  </select>
  <div class="trigger-sep"></div>
  <label data-i18n="pretrig">Pre-trig</label>
  <input type="number" id="trigger-pretrig" value="1000" min="10" max="50000" step="1">
  <div class="trigger-sep"></div>
  <button id="trigger-force-btn" data-i18n="force_trigger">Force Trigger</button>
</div>

<div id="var-selector"></div>

<main id="debug-main">
  <section id="chart-watch-wrap">
    <div id="enum-tooltip"></div>
    <div id="chart-wrap">
      <canvas id="chart"></canvas>
      <button
        id="chart-legend-toggle"
        type="button"
        aria-expanded="true"
        aria-controls="chart-legend"
        data-i18n-title="hide_channel_legend_tip"
        title="隐藏通道列表"
      ><span aria-hidden="true">&#9776;</span></button>
      <div id="chart-legend" class="is-visible" aria-label="Channel layout" aria-hidden="false"></div>
      <div id="split-panel-control" class="split-panel-control" hidden>
        <span class="split-panel-label" data-i18n="split_panel">独立通道</span>
        <span id="split-panel-name" class="split-panel-name"></span>
        <button
          id="split-panel-merge"
          type="button"
          data-i18n="merge_channel"
          data-i18n-title="merge_channel_tip"
          title="将此通道合并回主面板"
        >合并</button>
      </div>
      <div id="y-axis-hit" class="axis-hit-region axis-hit-y" data-i18n-title="y_axis_tip" title="纵轴：滚轮缩放；按住鼠标左键拖动；双击恢复自动范围"></div>
      <div id="x-axis-hit" class="axis-hit-region axis-hit-x" data-i18n-title="x_axis_tip" title="横轴：滚轮缩放；按住鼠标左键拖动；双击恢复默认视图"></div>
      <div id="tooltip"></div>
      <div id="cursor-a" class="cursor-line" style="display:none;"></div>
      <div id="cursor-b" class="cursor-line" style="display:none;"></div>
      <div id="cursor-measure-panel" style="display:none;"></div>
    </div>
    <div id="watch-resizer"></div>
    <div id="watch-panel">
      <div class="panel-header">
        <div class="panel-title">
          <span class="panel-dot"></span>
          <span data-i18n="watch">监视</span>
        </div>
        <div class="panel-actions">
          <span id="watch-count" class="panel-count">0 ch</span>
          <button id="watch-columns-btn" class="panel-btn" data-i18n-title="columns_tip" data-i18n="columns">列</button>
          <button id="watch-collapse" class="panel-btn panel-btn-close" data-i18n-title="collapse_watch" title="折叠监视面板">&#x2715;</button>
        </div>
      </div>
      <div id="watch-columns-menu" class="columns-menu" aria-hidden="true"></div>
      <div id="watch-table-wrap">
        <table id="watch-table">
          <thead>
            <tr id="watch-table-head-row"></tr>
          </thead>
          <tbody id="watch-tbody"></tbody>
        </table>
      </div>
    </div>
  </section>

  <div id="minimap-wrap">
    <canvas id="minimap-canvas"></canvas>
    <div id="minimap-viewport"></div>
    <div id="cursor-readout"></div>
  </div>

  <section id="raw-log-panel" data-open="false">
    <div class="panel-resizer" title="Drag to resize"></div>
    <div class="panel-header">
      <div class="panel-title">
        <span class="panel-dot"></span>
        <span data-i18n="raw_log">原始日志</span>
      </div>
      <div class="panel-actions">
        <span id="raw-log-count" class="panel-count">0 lines</span>
        <button id="raw-log-save" class="panel-btn" data-i18n-title="save_raw_log_tip" data-i18n="save">保存</button>
        <button id="raw-log-clear" class="panel-btn" data-i18n-title="clear_log" data-i18n="clear">清除</button>
        <button id="raw-log-close" class="panel-btn panel-btn-close" data-i18n-title="close_panel" title="关闭面板">&#x2715;</button>
      </div>
    </div>
    <pre id="raw-log"></pre>
  </section>
  <section id="inspector-panel" aria-hidden="true"></section>
</main>

<div id="threshold-overlay" class="config-overlay" aria-hidden="true">
  <div class="config-dialog" role="dialog" aria-modal="true" aria-labelledby="threshold-title">
    <h2 id="threshold-title" data-i18n="thresholds">阈值</h2>
    <div class="config-grid">
      <div class="config-field full">
        <label for="threshold-channel" data-i18n="channel">通道</label>
        <select id="threshold-channel"></select>
      </div>
      <div class="config-field">
        <label for="threshold-warn-low" data-i18n="warn_low">警告下限</label>
        <input id="threshold-warn-low" type="number" step="0.1">
      </div>
      <div class="config-field">
        <label for="threshold-warn-high" data-i18n="warn_high">警告上限</label>
        <input id="threshold-warn-high" type="number" step="0.1">
      </div>
      <div class="config-field">
        <label for="threshold-alarm-low" data-i18n="alarm_low">报警下限</label>
        <input id="threshold-alarm-low" type="number" step="0.1">
      </div>
      <div class="config-field">
        <label for="threshold-alarm-high" data-i18n="alarm_high">报警上限</label>
        <input id="threshold-alarm-high" type="number" step="0.1">
      </div>
    </div>
    <div class="config-actions">
      <button id="threshold-clear" class="panel-btn" data-i18n="clear">清除</button>
      <button id="threshold-cancel" class="panel-btn" data-i18n="cancel">取消</button>
      <button id="threshold-apply" class="panel-btn" data-i18n="apply">应用</button>
    </div>
  </div>
</div>
<div id="shutdown-overlay">
  <h2 data-i18n="server_shutdown">服务器已关闭</h2>
  <p data-i18n="server_stopped_msg">可视化服务器已停止。</p>
  <p data-i18n="close_tab_msg">可以关闭此标签页。</p>
</div>

<div id="help-overlay" aria-hidden="true">
  <div id="help-modal" role="dialog" aria-modal="true" aria-labelledby="help-modal-title">
    <div id="help-modal-header">
      <h2 id="help-modal-title" data-i18n="help_title">使用说明</h2>
      <button id="help-close-btn" data-i18n-title="close_esc" title="关闭 (Esc)">&times;</button>
    </div>
    <div id="help-modal-body">
      <div class="help-section"><h3 data-i18n="help_chart">图表交互</h3><ul id="help-chart-list"></ul></div>
      <div class="help-section"><h3 data-i18n="help_var_selector">变量选择器</h3><ul id="help-var-list"></ul></div>
      <div class="help-section"><h3 data-i18n="help_trigger_sys">触发系统</h3><ul id="help-trigger-list"></ul></div>
      <div class="help-section"><h3 data-i18n="help_watch_panel">Watch 面板</h3><ul id="help-watch-list"></ul></div>
      <div class="help-section"><h3 data-i18n="help_minimap">缩略图</h3><ul id="help-minimap-list"></ul></div>
      <div class="help-section"><h3 data-i18n="help_cursors">测量光标</h3><ul id="help-cursors-list"></ul></div>
      <div class="help-section"><h3 data-i18n="help_export">数据导出</h3><ul id="help-export-list"></ul></div>
      <div class="help-section"><h3 data-i18n="help_shortcuts">键盘快捷键</h3><table class="help-kbd-table" id="help-kbd-table"></table></div>
      <div class="help-section"><h3 data-i18n="help_rawlog">Raw Log 面板</h3><ul id="help-rawlog-list"></ul></div>
      <div class="help-section"><h3 data-i18n="help_pause_resume">暂停/恢复</h3><ul id="help-pause-list"></ul></div>
    </div>
  </div>
</div>`}function te(e,t){let n=t===`SuperWatch`?5e4:2,r=t===`SuperWatch`?5e4:1e4,i=document.createElement(`script`);i.textContent=`
    var CONFIG = {
      minPoints: ${n},
      maxPoints: ${r},
      title: "MKLink ${t}",
      mode: "${t}",
      lang: ${JSON.stringify(f.value)},
      apiBase: ${JSON.stringify(l)},
      deviceConnected: ${c.deviceConnected}
    };
  `,e.appendChild(i);let a=document.createElement(`script`);a.src=D,a.onload=()=>{I||(typeof window.setLang==`function`&&window.setLang(f.value),ne(e))},e.appendChild(a)}function ne(e){let t=document.createElement(`script`);t.src=O,t.onload=()=>{if(I)return;let e=window.__waveformViewers;e&&!e[c.mode]?e[c.mode]={es:window.es}:e?.[c.mode]&&(e[c.mode].es=window.es),e?.[c.mode]&&(e[c.mode].setDeviceConnected?.(c.deviceConnected),V(e[c.mode]),e[c.mode].configureBinaryChannels?.(g),W(),N&&e[c.mode].updateAcquisitionStatus?.(N),v&&=(e[c.mode].acceptBinaryBatch?.(v,g),null))},e.appendChild(t)}return(t,n)=>(a(),e(`div`,{ref_key:`container`,ref:p,class:s([`waveform-viewer`,{"superwatch-desktop":c.mode===`SuperWatch`}])},null,2))}}),[[`__scopeId`,`data-v-d82ad4e7`]]);export{x as i,w as n,E as r,A as t};