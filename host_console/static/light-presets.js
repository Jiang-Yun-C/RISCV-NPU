// Deliberately bounded shortcuts. Questions, negation, partial lamp targets and
// combined commands never match these actions.
const on=['开灯','打开灯','打开所有灯','打开全部灯','打开四个灯','打开四盏灯','把灯打开','把所有灯打开','四个灯都打开','全部开灯'];
const off=['关灯','关闭灯','关闭所有灯','关闭全部灯','关闭四个灯','关闭四盏灯','把灯关掉','把灯关闭','把所有灯关掉','四个灯都关掉','全部关灯'];
export const LIGHT_PRESETS=Object.freeze({on:Object.freeze({action:'on',title:'打开灯光',success:'已开灯 · 四盏灯保持常亮',values:45}),off:Object.freeze({action:'off',title:'关闭灯光',success:'已关灯 · 四盏灯已全部熄灭',values:0})});
const instructionCache=new Map([...on.map(text=>[text,LIGHT_PRESETS.on]),...off.map(text=>[text,LIGHT_PRESETS.off])]);
export function resolveLightRequest(text){
  if(typeof text!=='string')return null;
  const normalized=text.normalize('NFKC').trim().replace(/[。.!！]+$/u,'');
  const s=normalized.replace(/^(?:请帮我|请|帮我|麻烦你|麻烦)/u,'');
  return instructionCache.get(s)||null;
}
export function isNegatedLightRequest(text){return typeof text==='string'&&/不要|别|禁止|不许|不能|不想/u.test(text)&&/灯|小星星/u.test(text);}
