import json,time
from pathlib import Path

class LifecycleEvidence:
 def __init__(self,page,path):
  self.page=page;self.path=Path(path);self.path.mkdir(parents=True,exist_ok=False);self.start=time.monotonic();self.events=[];self.pending={}
  page.context.tracing.start(screenshots=False,snapshots=False,sources=False)
  page.expose_binding('__s12Lifecycle',lambda source,event:self.record('js',event))
  page.add_init_script(JS)
  page.on('request',self.request)
  page.on('response',lambda r:self.record('response',{'url':r.url,'status':r.status,'type':r.request.resource_type,'navigation':r.request.is_navigation_request()}))
  page.on('requestfinished',lambda r:self.finished(r,'requestfinished'))
  page.on('requestfailed',lambda r:self.finished(r,'requestfailed'))
  page.on('framenavigated',lambda f:self.record('commit',{'url':f.url,'main':f==page.main_frame}))
  page.on('domcontentloaded',lambda:self.record('DOMContentLoaded',{'url':page.url}))
  page.on('load',lambda:self.record('load',{'url':page.url}))
  page.on('dialog',self.dialog)
  page.on('pageerror',lambda e:self.record('pageerror',{'message':str(e),'stack':e.stack}))
 def record(self,kind,data):
  row={'ms':round((time.monotonic()-self.start)*1000,3),'event':kind,**data};self.events.append(row)
 def request(self,r):
  row={'id':id(r),'url':r.url,'method':r.method,'type':r.resource_type,'navigation':r.is_navigation_request()};self.pending[id(r)]=row;self.record('request',row)
 def finished(self,r,kind):
  self.pending.pop(id(r),None);self.record(kind,{'id':id(r),'url':r.url,'failure':r.failure if kind=='requestfailed' else None})
 def dialog(self,d):
  self.record('dialog',{'type':d.type,'message':d.message});d.dismiss()
 def finish(self,error=None):
  self.record('finish',{'url':self.page.url,'error':str(error) if error else None,'pending':list(self.pending.values())})
  (self.path/'events.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in self.events))
  try:self.page.screenshot(path=str(self.path/'last.png'),timeout=3000)
  except Exception as e:self.record('screenshot-error',{'type':type(e).__name__})
  try:self.page.context.tracing.stop(path=str(self.path/'trace.zip'))
  except Exception as e:self.record('trace-error',{'type':type(e).__name__})

JS=r'''(() => {
 let leaving=false;const audios=[];
 const send=(kind,data={})=>{try{void window.__s12Lifecycle({kind,href:location.href,readyState:document.readyState,jsMs:performance.now(),leaving,...data}).catch(()=>{});}catch{}};
 const snapshot=()=>[...new Set([...audios,...document.querySelectorAll('audio,video')])].map(a=>({id:a.id,src:a.getAttribute('src'),readyState:a.readyState,networkState:a.networkState,paused:a.paused,preload:a.preload}));
 const create=document.createElement.bind(document);document.createElement=(tag,...args)=>{const n=create(tag,...args);if(String(tag).toLowerCase()==='audio')audios.push(n);return n;};
 const nativeFetch=window.fetch;window.fetch=function(input,...args){const url=String(input?.url||input);if(url.includes('storage-usage'))send('usage-fetch-start',{url,stack:new Error().stack});return nativeFetch.call(this,input,...args);};
 const read=Blob.prototype.arrayBuffer;Blob.prototype.arrayBuffer=function(...args){if(leaving)send('late-file-read',{name:this.name||'(blob)'});return read.apply(this,args);};
 window.addEventListener('beforeunload',()=>{leaving=true;send('beforeunload-early',{audios:snapshot()});});
 window.addEventListener('pagehide',e=>send('pagehide-early',{persisted:e.persisted,audios:snapshot()}));
 document.addEventListener('DOMContentLoaded',()=>send('DOMContentLoaded-js'));
 window.addEventListener('load',()=>{send('load-js');window.addEventListener('beforeunload',()=>send('beforeunload-late',{audios:snapshot()}));window.addEventListener('pagehide',e=>send('pagehide-late',{persisted:e.persisted,audios:snapshot()}));});
 window.addEventListener('unhandledrejection',e=>send('unhandledrejection',{message:String(e.reason),stack:e.reason?.stack}));
 window.addEventListener('error',e=>send('window-error',{message:e.message,filename:e.filename,line:e.lineno}));
 send('init');
})();'''
