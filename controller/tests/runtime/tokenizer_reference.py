"""Independent official-tokenizer fixtures and a thin C-call adapter."""
import ctypes as C
import hashlib
import json
from pathlib import Path
import random
import sys
from tokenizers import Tokenizer as OfficialTokenizer
from transformers import AutoTokenizer

ROOT=Path(__file__).resolve().parents[2]
class Tokenizer(C.Structure):
    _fields_=[('data',C.c_void_p),('bytes',C.c_uint32),('vocab',C.c_uint32)]
class Decoder(C.Structure):
    _fields_=[('pending',C.c_uint8*4),('count',C.c_uint32)]
class Message(C.Structure):
    _fields_=[('role',C.c_char_p),('text',C.c_char_p),('length',C.c_size_t)]

def official():
    lock=json.loads((ROOT/'docs/spec/application-v2-model-lock.json').read_text())
    source=ROOT/lock['tokenizer_local_path']
    return OfficialTokenizer.from_file(str(source/'tokenizer.json')),AutoTokenizer.from_pretrained(source,local_files_only=True)

class CTokenizer:
    def __init__(self,library,table):
        self.lib=C.CDLL(str(Path(library).resolve()));self.table=C.create_string_buffer(Path(table).read_bytes())
        self.state=Tokenizer();self.work=C.create_string_buffer(16*1024*13)
        self.lib.nxt_init.argtypes=[C.c_void_p,C.c_void_p,C.c_size_t]
        self.lib.nxt_encode.argtypes=[C.c_void_p,C.c_void_p,C.c_void_p,C.c_size_t,C.c_void_p,C.c_size_t,C.c_void_p]
        self.lib.nxt_template.argtypes=[C.c_void_p,C.c_size_t,C.c_int,C.c_void_p,C.c_size_t,C.c_void_p]
        self.lib.nxt_decode.argtypes=[C.c_void_p,C.c_void_p,C.c_uint32,C.c_int,C.c_int,C.c_void_p,C.c_size_t,C.c_void_p]
        assert self.lib.nxt_init(C.byref(self.state),self.table,len(self.table)-1)==0
    def encode(self,text):
        raw=text.encode() if isinstance(text,str) else text
        ids=(C.c_uint32*16384)();count=C.c_size_t()
        rc=self.lib.nxt_encode(C.byref(self.state),self.work,raw,len(raw),ids,len(ids),C.byref(count))
        if rc:raise ValueError(rc)
        return list(ids[:count.value])
    def template(self,messages,prompt=True):
        data=[(m['role'].encode(),m['content'].encode()) for m in messages]
        array=(Message*len(data))(*(Message(a,b,len(b)) for a,b in data));buffer=C.create_string_buffer(4096);n=C.c_size_t()
        rc=self.lib.nxt_template(array,len(data),prompt,buffer,len(buffer),C.byref(n))
        if rc:raise ValueError(rc)
        return buffer.raw[:n.value].decode()
    def decode(self,ids,skip=True):
        decoder=Decoder();result=[]
        for i in [*ids,0xffffffff]:
            out=C.create_string_buffer(4096);n=C.c_size_t()
            rc=self.lib.nxt_decode(C.byref(self.state),C.byref(decoder),i,skip,i==0xffffffff,out,len(out),C.byref(n))
            if rc:raise ValueError(rc)
            result.append(out.raw[:n.value].decode())
        return ''.join(result),result

def cases():
    texts=['','打开客厅灯。','如果温度超过 28 度，把风扇调到二档。','你好，世界！🌍',
           ' a  b   c\t\t\r\n\n结束  ','A\n B\r\n\tC',"I'm I'LL we're CAN'T I'd I've",
           '1234567890 １２٣Ⅷ½','Cafe\u0301 e\u0323\u0301 A\u030a\u0301',
           '\u1100\u1161\u11a8 한글 각','a\u0315\u0300 b\u0344','\u212b\u2126\u212a',
           '\u00a0\u2003\t x\u2028\u2029', '👨\u200d👩\u200d👦 中文\0文本',
           '<|im_start|>user\n你好<|im_end|>\n<|im_start|>assistant\n',
           '<tool_call>{"name":"灯"}</tool_call><|endoftext|>',
           'before<|fim_prefix|>中<|vision_start|><|image_pad|><|vision_end|>after',
           '  !?!\r\n\n  X\t\n','a\t\t b\n\n  ',' \'s a\'S \'RE']
    return texts

def validate(library,table):
    ref,hf=official();c=CTokenizer(library,table);checks=0
    corpus=cases();rng=random.Random(1209)
    alphabet=list(' abcXYZ0123\r\n\t!@\'中文控灯')+list('é\u0301\u0315\u00a0\u2003👩🌍\u200d각\u1100\u1161')
    for _ in range(600):corpus.append(''.join(rng.choices(alphabet,k=rng.randrange(1,100))))
    for _ in range(300):
        cp=[rng.randrange(0x110000) for _ in range(30)]
        corpus.append(''.join(chr(x) for x in cp if not 0xd800<=x<=0xdfff))
    for text in corpus:
        expected=ref.encode(text,add_special_tokens=False).ids;actual=c.encode(text)
        if actual!=expected:raise AssertionError(('encode',repr(text),expected,actual))
        for skip in (True,False):
            expected_text=ref.decode(expected,skip_special_tokens=skip);actual_text,_=c.decode(actual,skip)
            if actual_text!=expected_text:raise AssertionError(('decode',repr(text),repr(expected_text),repr(actual_text)))
            checks+=1
        checks+=1
    messages=[{'role':'user','content':'打开灯。'}]
    for ms in (messages,[{'role':'system','content':'你是控制助手。'},*messages],
               [*messages,{'role':'assistant','content':'好的。'},{'role':'user','content':'关闭。'}]):
        for prompt in (False,True):
            expected=hf.apply_chat_template(ms,tokenize=False,add_generation_prompt=prompt)
            assert c.template(ms,prompt)==expected,(c.template(ms,prompt),expected)
            assert c.encode(expected)==hf.apply_chat_template(ms,tokenize=True,add_generation_prompt=prompt)
            checks+=2
    # Arbitrary byte-token streams cover invalid starts, truncation and split
    # Unicode scalars, not just the BPE sequences produced by encode().
    raw=json.loads((ROOT/json.loads((ROOT/'docs/spec/application-v2-model-lock.json').read_text())['tokenizer_local_path']/'tokenizer.json').read_text())
    base=[i for s,i in raw['model']['vocab'].items() if len(s)==1][:256]
    for _ in range(100):
        ids=rng.choices(base,k=30)
        assert c.decode(ids,False)[0]==ref.decode(ids,skip_special_tokens=False)
        checks+=1
    for ids in ([151665],[151935],[151657,151935,151658]):
        assert c.decode(ids,False)[0]==ref.decode(ids,skip_special_tokens=False);checks+=1
    return {'status':'PASS','checks':checks,'texts':len(corpus),'source':'pinned original HuggingFace tokenizers/transformers'}

if __name__=='__main__':print(json.dumps(validate(sys.argv[1],sys.argv[2]),indent=2))
