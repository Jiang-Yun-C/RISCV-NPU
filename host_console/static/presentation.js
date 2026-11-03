// Presentation pacing only. No model timing, device work, randomness or network.
export const PRESENTATION=Object.freeze({firstCharacterMs:600,characterMs:35,maxReplyMs:2500,toolPreparationMs:800});
export function characters(text){return typeof Intl.Segmenter==='function'?[...new Intl.Segmenter('zh-CN',{granularity:'grapheme'}).segment(text)].map(x=>x.segment):Array.from(text);}
export function replyTiming(text){const parts=characters(text),steps=Math.max(0,parts.length-1),interval=steps?Math.min(PRESENTATION.characterMs,(PRESENTATION.maxReplyMs-PRESENTATION.firstCharacterMs)/steps):0;return{parts,initial:parts.length?PRESENTATION.firstCharacterMs:0,interval,plannedMs:parts.length?PRESENTATION.firstCharacterMs+interval*steps:0};}
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
export async function presentReply(text,render,{wait=pause,now=()=>performance.now()}={}){
  const timing=replyTiming(text),start=now();let shown=0;
  if(!timing.parts.length){render('');return timing;}
  while(shown<timing.parts.length){
    const elapsed=now()-start;
    const due=elapsed<timing.initial?0:timing.interval?Math.min(timing.parts.length,1+Math.floor((elapsed-timing.initial)/timing.interval)):timing.parts.length;
    if(due>shown){shown=due;render(timing.parts.slice(0,shown).join(''));}
    if(shown<timing.parts.length)await wait(Math.max(1,timing.initial+shown*timing.interval-(now()-start)));
  }
  return timing;
}
export async function finishPreparation(start,{now=()=>performance.now(),wait=pause}={}){const remaining=PRESENTATION.toolPreparationMs-(now()-start);if(remaining>0)await wait(remaining);}
