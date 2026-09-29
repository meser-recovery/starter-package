/* Extends the approved pilot's procedural waveform/object language. No text-card fallback. */
function label(s,x,y,color=C.muted){text(s,x,y,25,color,600)}
function compressedTime(t,progress,shared){let delta=0;for(const[a,b]of shared){if(t>=b)delta+=(b-a-.35)*progress;else if(t>a)delta+=(t-a)/(b-a)*(b-a-.35)*progress}return t-delta}
function audioLane(x,y,w,segments,color,progress=0,shared=[]){
  const reduction=clamp(progress),total=24;
  const removed=shared.reduce((sum,[a,b])=>sum+(b-a-.35)*reduction,0);
  const at=t=>x+compressedTime(t,reduction,shared)/total*w;
  line(x,y,at(total),y,C.line,3);
  for(const[a,b]of segments){ctx.beginPath();for(let t=a;t<=b;t+=.025){const amp=Math.min(1,(t-a)*8,(b-t)*8)*(20+32*Math.abs(Math.sin(t*16)));line(at(t),y-amp,at(t),y+amp,color,3)}}
  return at(total)-x;
}
const SPK=[[0,3],[7,10],[14,17],[21,24]],RU=[[3,7],[10,14],[17,21]];
function bilingual(p){
  base('19','Двуязычная запись · дорожка русского перевода');
  person(182,442,C.blue);person(182,666,C.teal);label('Иврит',126,532,C.blue);label('Русский',126,756,C.teal);
  alpha(1-ramp(p,.6,.83)*.7,()=>audioLane(380,458,1270,SPK,C.blue));audioLane(380,682,1270,RU,C.teal);
  let pos=380+1270*clamp(p/.58);if(p<.6){line(pos,355,pos,775,C.ink,3);label('Оригинал → перевод',690,855)}else{headphones(1745,682,C.teal);label('Для анализа — русский перевод',640,865);for(const[a,b]of SPK)box(380+a/24*1270,622,(b-a)/24*1270,120,3,'#657b8e15')}
}
function oneTranslator(p){
  base('20','Длинные паузы становятся короче');const segments=[[0,3],[7,10],[15,17],[21,24]],silences=[[3,7],[10,15],[17,21]],progress=ramp(p,.4,.82);
  label('Исходная дорожка',125,385);audioLane(430,455,1290,segments,C.teal);
  for(const[a,b]of silences){box(430+a/24*1290,393,(b-a)/24*1290,123,3,'#657b8e20');alpha(ramp(p,.18,.35),()=>text('≥ 2 c',430+(a+b)/48*1290,549,23,C.muted,500,'center'))}
  label('После обработки',125,660);const width=audioLane(430,730,1290,segments,C.teal,progress,silences);line(430,832,430+width,832,C.teal,4);
  alpha(progress,()=>{text('≈ 0,35 c между фразами',980,904,28,C.ink,700,'center');text('Речь сохранена',430+width/2,808,25,C.teal,500,'center')});
}
const R1=[[1,4],[11,14],[18,22]],R2=[[4,8],[12,15],[20,22]],COMMON=[[8,11],[15,18],[22,24]];
function translators(p,common){
  base(common?'22':'21',common?'Сокращается только общая тишина':'Два переводчика · общий порядок разговора');
  label('Переводчик 1',114,417,C.teal);label('Переводчик 2',114,619,C.gold);
  ctx.fillStyle=C.bg;ctx.fillRect(94,993,850,80);circle(102,1022,5,C.teal);text('Переводчик 1',124,1030,23,C.teal);circle(366,1022,5,C.gold);text('Переводчик 2',388,1030,23,C.gold);
  const shorten=common?ramp(p,.42,.78):0;
  const sequential=common?0:ramp(p,.32,.52)*(1-ramp(p,.58,.7));
  for(const[y,segments,color]of [[430,R1,C.teal],[630,R2,C.gold]])audioLane(410+(y===630?sequential*620:0),y,1250*(1-sequential*.5),segments,color,shorten,COMMON);
  if(common){alpha(1-shorten,()=>{for(const[a,b]of COMMON){box(410+compressedTime(a,shorten,COMMON)/24*1250,347,(compressedTime(b,shorten,COMMON)-compressedTime(a,shorten,COMMON))/24*1250,360,3,'#bd761130')}});alpha(ramp(p,.16,.34),()=>{box(410+compressedTime(12,shorten,COMMON)/24*1250,347,2/24*1250,360,0,'#087df117');label('Есть речь → сохраняем',1130,325,C.blue)});alpha(shorten,()=>{label('Обе дорожки сокращены синхронно',635,816,C.teal);file(1610,849,C.teal,'MP3',.58)});}
  else{const seq=ramp(p,.32,.52)*(1-ramp(p,.58,.7));alpha(seq,()=>{line(412,830,1660,830,C.red,3);text('По очереди — порядок нарушается',650,900,30,C.red,600);line(885,790,947,858,C.red,5);line(947,790,885,858,C.red,5)});alpha(ramp(p,.72,.9),()=>{line(410,330,410,730,C.teal,4);line(1660,330,1660,730,C.teal,4);text('Общее время · совпадения речи сохранены',610,872,30,C.teal,600)});}
}
function workflow(p){
  base('60','От отдельных дорожек к готовому результату');const save=ramp(p,.12,.28),edit=ramp(p,.3,.55),done=ramp(p,.62,.85);
  for(let i=0;i<3;i++){file(mix(260,640,save),420+i*130,[C.blue,C.teal,C.gold][i],['SPK','RU','MIC'][i],.68)}
  alpha(save,()=>recordFolder(680,555,save,done,p));alpha(1-save,()=>label('Zoom',212,320));
  alpha(edit,()=>{label('Независимая обработка дорожек',1120,340);for(let i=0;i<3;i++)wave(1160,445+i*90,560,54,i,[C.blue,C.teal,C.gold][i],{exclude:i===2?done:0,cut:done});});
  alpha(done,()=>{file(1220,866,C.teal,'RU',.55);file(1450,866,C.blue,'MP3',.55);circle(1650,858,35,C.white,C.teal);check(1650,858);label('Проект',1608,940)});
  alpha(ramp(p,.9,1),()=>{ctx.fillStyle='#f1f5faed';ctx.fillRect(360,405,1200,305);text('Спасибо за внимание',960,530,58,C.ink,700,'center');text('Всего доброго',960,613,36,C.muted,400,'center')});
}
Object.assign(renderers,{'019':bilingual,'020':oneTranslator,'021':p=>translators(p,false),'022':p=>translators(p,true),'060':workflow});
for(const [id,title] of Object.entries({'019':'Двуязычная запись','020':'Один переводчик','021':'Два переводчика','022':'Общая тишина','060':'Итог'})){const option=document.createElement('option');option.value=id;option.textContent=id+' · '+title;document.querySelector('#scene').append(option)}

document.querySelector('#scene').value=selected;window.renderFrame(selected,p);
