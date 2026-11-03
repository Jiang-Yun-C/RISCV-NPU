"""Register one bounded tool package; never evaluate model-generated code."""
import hashlib,json,re,threading
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def validated_call(body):
    if not isinstance(body,dict)or set(body)!={'call_id','tool','arguments','source_entry_id','source_uart_sha256'}:raise ValueError('工具调用字段无效')
    if not isinstance(body['call_id'],str)or not re.fullmatch(r'[a-zA-Z0-9-]{16,80}',body['call_id']):raise ValueError('工具调用ID无效')
    registry=json.loads((ROOT/'static/tool-registry.json').read_text(encoding='utf8'))
    for name,digest in registry['files'].items():
        path=(ROOT/name).resolve()
        if ROOT not in path.parents or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:raise ValueError('代码包摘要不匹配')
    doc=json.loads((ROOT/'static/prepared-tool-tokens.json').read_text(encoding='utf8'))
    if body['tool']!='twinkle' or body['arguments']!={'effect':'twinkle','bpm':120,'repeat':1}:raise ValueError('仅允许已登记的小星星代码包')
    if body['source_entry_id']!=doc['entry_id']or body['source_uart_sha256']!=doc['original_uart_sha256']:raise ValueError('调用token来源不匹配')
    return body

def install_tool_dispatch(bridge_class):
    def invoke(self,body,owner):
        call=validated_call(body)
        with self.lock:
            self._check_owner(owner)
            calls=getattr(self,'tool_invocations',None)
            if calls is None:self.tool_invocations={};calls=self.tool_invocations
            if call['call_id']in calls:
                old=calls[call['call_id']]
                if old['owner']!=owner or old['call']!=call:raise ValueError('调用ID不能绑定另一请求')
                return dict(id=old['effect_id'],status='ALREADY_INVOKED',deduplicated=True,call_id=call['call_id'])
            from rhythm_effect import model_plan
            result=self.rhythm_start(model_plan()['user_prompt'],owner)
            calls[call['call_id']]={'owner':owner,'call':call,'effect_id':result['id']}
            self.effect_link.state.update(tool='twinkle',package='twinkle_v1',tool_call_id=call['call_id'],dispatch_source='PREGENERATED_VERIFIED_MODEL_TOKENS',user_interaction='CHAT_SEND_AUTO_DISPATCH')
            return dict(result,call_id=call['call_id'],deduplicated=False)
    bridge_class.tool_invoke=invoke
    return bridge_class
