export function isTwinkleRequest(text){const s=text.normalize('NFKC').trim().replace(/[。.!！?？]+$/u,'');if(/不要|别|禁止|不许|不能|不想|不闪|不播放|只|仅|LED|第|一个灯|两个灯|三个灯|两灯|三灯|是什么|为什么|是否|会不会|吗/u.test(s))return false;return s==='小星星'||(s.includes('小星星')&&/播放|闪|轮流|来一首|来一段|来个|运行|执行/u.test(s));}
export function verifyTokens(prepared,entry){
 // A cache may contain several base64 chunks; decode each separately.
 const decoder=new TextDecoder('utf8',{fatal:true});const text=entry.uart.chunks.map(c=>decoder.decode(Uint8Array.from(atob(c),x=>x.charCodeAt(0)),{stream:true})).join('')+decoder.decode();
 const records=[];
 for(const line of text.split('\n')){
  const m=/^T25 STREAM 1 (TOKEN|TEXT) session=([0-9a-f]{16}) sequence=([0-9a-f]{16}) index=([0-9a-f]{16}) ticks=([0-9a-f]{16}) token=([0-9a-f]{16}) error=([0-9a-f]{16}) data=(-|[0-9a-f]+)$/.exec(line);
  if(!m)continue;const i=parseInt(m[4],16),id=parseInt(m[6],16);if(parseInt(m[7],16))throw Error('原始token有错误');
  if(m[1]==='TOKEN'){if(i!==records.length+1)throw Error('原始token索引不连续');records.push({index:i,token_id:id,text_hex:''});}
  else{const r=records[i-1];if(!r||r.token_id!==id||m[8]==='-')throw Error('原始TEXT未绑定TOKEN');r.text_hex+=m[8];}
 }
 if(prepared.tokens.length!==records.length||records.length!==19||prepared.tokens.some((t,i)=>t.index!==records[i].index||t.token_id!==records[i].token_id||t.text_hex!==records[i].text_hex))throw Error('预生成token与原始UART不一致');
 const joined=new TextDecoder('utf8',{fatal:true}).decode(Uint8Array.from(records.flatMap(t=>(t.text_hex.match(/../g)||[]).map(h=>parseInt(h,16)))));
 if(joined!==entry.text||prepared.entry_id!==entry.id||prepared.original_uart_sha256!==entry.uart.sha256||prepared.is_live_inference!==false||prepared.verified_eos!==true)throw Error('预生成调用身份不匹配');
 const rawCall=JSON.parse(joined),call=Array.isArray(rawCall)&&rawCall.length===1?rawCall[0]:rawCall;
 if(!call||Object.keys(call).sort().join()!=='bpm,effect,repeat'||call.effect!=='twinkle'||call.bpm!==120||call.repeat!==1)throw Error('工具调用不属于登记代码包');return call;
}
