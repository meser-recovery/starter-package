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
function archiveContainer(p){
  base('11','Одна запись · связанные материалы');const emerge=ramp(p,.05,.24),history=ramp(p,.35,.55),results=ramp(p,.62,.82);
  box(240,292,1440,570,28,'#e0edf9');text('Запись собрания',285,345,28,C.ink,700);
  for(let i=0;i<3;i++)alpha(emerge,()=>file(430+i*145,480,[C.blue,C.teal,C.gold][i],['SPK','RU 1','RU 2'][i],.8));
  label('Исходники',568,615);
  alpha(history,()=>{line(1030,465,1500,465,C.teal,5);for(let i=0;i<3;i++){circle(1030+i*220,465,20,C.white,C.teal);text('v'+(i+1),1030+i*220,522,22,C.ink,600,'center')}label('История проекта',1095,390);});
  alpha(results,()=>{for(let i=0;i<3;i++){line(1030+i*220,485,1030+i*220,665,C.line,3);file(1030+i*220,719,[C.blue,C.teal,C.gold][i],'MP3',.56)}label('Спикерские · MP3',1080,825);file(575,732,C.teal,'RU',.6);label('Версии для анонса',455,825)});
  alpha(ramp(p,.83,1),()=>{ctx.strokeStyle=C.blue;ctx.lineWidth=4;ctx.strokeRect(253,305,1414,544);check(1610,345)});
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
  label('Переводчик 1',114,417,C.teal);label('Переводчик 2',114,619,C.blue);
  const shorten=common?ramp(p,.42,.78):0;
  const sequential=common?0:ramp(p,.32,.52)*(1-ramp(p,.58,.7));
  for(const[y,segments,color]of [[430,R1,C.teal],[630,R2,C.blue]])audioLane(410+(y===630?sequential*620:0),y,1250*(1-sequential*.5),segments,color,shorten,COMMON);
  if(common){alpha(1-shorten,()=>{for(const[a,b]of COMMON){box(410+compressedTime(a,shorten,COMMON)/24*1250,347,(compressedTime(b,shorten,COMMON)-compressedTime(a,shorten,COMMON))/24*1250,360,3,'#bd761130')}});alpha(ramp(p,.16,.34),()=>{box(410+compressedTime(12,shorten,COMMON)/24*1250,347,2/24*1250,360,0,'#087df117');label('Есть речь → сохраняем',1130,325,C.blue)});alpha(shorten,()=>{label('Обе дорожки сокращены синхронно',635,816,C.teal);file(1610,849,C.teal,'MP3',.58)});}
  else{const seq=ramp(p,.32,.52)*(1-ramp(p,.58,.7));alpha(seq,()=>{line(412,830,1660,830,C.red,3);text('По очереди — порядок нарушается',650,900,30,C.red,600);line(885,790,947,858,C.red,5);line(947,790,885,858,C.red,5)});alpha(ramp(p,.72,.9),()=>{line(410,330,410,730,C.teal,4);line(1660,330,1660,730,C.teal,4);text('Общее время · совпадения речи сохранены',610,872,30,C.teal,600)});}
}
function projectAndFinal(p,linked){
  base(linked?'50':'44',linked?'Финальная версия связана с состоянием проекта':'Редактируемый проект и готовый звук');
  browserFrame(155,335,885,510,'Проект · монтаж и настройки');
  for(let i=0;i<3;i++){label(['SPK','RU','MIC'][i],183,490+i*105,[C.blue,C.teal,C.gold][i]);wave(295,480+i*105,680,62,i,[C.blue,C.teal,C.gold][i],{cut:linked?ramp(p,.8,.95):ramp(p,.22,.44),gain:i===0?mix(.4,1,ramp(p,.1,.3)):1})}
  line(650,420,650,780,C.red,3);circle(420,804,9,C.teal);line(380,804,520,804,C.teal,3);
  const render=ramp(p,.48,.76);alpha(render,()=>{file(1455,596,C.blue,'MP3',1.85);play(1455,868,35,C.blue);text('Готовый звук',1455,354,34,C.ink,700,'center')});
  if(linked){line(1130,392,1130,818,C.line,4);for(let i=0;i<3;i++){circle(1130,422+i*180,19,i===1?C.teal:C.white,C.teal);text('v'+(i+1),1180,430+i*180,26,C.muted)}alpha(render,()=>{line(1149,602,1340,602,C.teal,5);check(1270,602);text('v2',1455,918,29,C.teal,700,'center');alpha(ramp(p,.8,.94),()=>{circle(1130,782,24,C.blue);text('v3',1180,790,26,C.blue);text('MP3 · v2',1455,970,22,C.muted,500,'center')})});}
  else{alpha(render,()=>{const q=ramp(p,.5,.75);circle(mix(1040,1370,q),596,13,C.blue);label('Монтаж можно продолжить',294,917,C.teal)})}
}
function workflow(p){
  base('60','От отдельных дорожек к готовому результату');const save=ramp(p,.12,.28),edit=ramp(p,.3,.55),done=ramp(p,.62,.85);
  for(let i=0;i<3;i++){file(mix(260,640,save),420+i*130,[C.blue,C.teal,C.gold][i],['SPK','RU','MIC'][i],.68)}
  alpha(save,()=>recordFolder(680,555,save,done,p));alpha(1-save,()=>label('Zoom',212,320));
  alpha(edit,()=>{browserFrame(1120,340,660,432,'Аудиоредактор');for(let i=0;i<3;i++)wave(1160,445+i*90,560,54,i,[C.blue,C.teal,C.gold][i],{exclude:i===2?done:0,cut:done});});
  alpha(done,()=>{file(1220,866,C.teal,'RU',.55);file(1450,866,C.blue,'MP3',.55);circle(1650,858,35,C.white,C.teal);check(1650,858);label('Проект',1608,940)});
  alpha(ramp(p,.9,1),()=>{ctx.fillStyle='#f1f5faed';ctx.fillRect(360,405,1200,305);text('Спасибо за внимание',960,530,58,C.ink,700,'center');text('Всего доброго',960,613,36,C.muted,400,'center')});
}
Object.assign(renderers,{'011':archiveContainer,'019':bilingual,'020':oneTranslator,'021':p=>translators(p,false),'022':p=>translators(p,true),'044':p=>projectAndFinal(p,false),'050':p=>projectAndFinal(p,true),'060':workflow});
for(const [id,title] of Object.entries({'011':'Архив','019':'Двуязычная запись','020':'Один переводчик','021':'Два переводчика','022':'Общая тишина','044':'Проект / MP3','050':'Состояние / результат','060':'Итог'})){const option=document.createElement('option');option.value=id;option.textContent=id+' · '+title;document.querySelector('#scene').append(option)}

document.querySelector('#scene').value=selected;window.renderFrame(selected,p);
