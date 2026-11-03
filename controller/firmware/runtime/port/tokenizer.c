#include "tokenizer.h"
#include <string.h>
#include <limits.h>
static uint32_t u32(const uint8_t *p) { return (uint32_t)p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24; }
static uint32_t hdr(const nxt_tokenizer *t,unsigned i) { return u32(t->data+4*i); }
static const uint8_t *table(const nxt_tokenizer *t,unsigned i) { return t->data+hdr(t,10+i); }
static uint32_t word(const uint8_t *p,uint32_t i) { return u32(p+4*i); }
int nxt_init(nxt_tokenizer *t,const void *data,size_t bytes) {
    if(!t||!data||bytes<128||bytes>5630976) return NXT_ARGUMENT;
    nxt_tokenizer v={(const uint8_t *)data,(uint32_t)bytes,0};
    if(hdr(&v,0)!=0x31544b4e||hdr(&v,1)!=1||hdr(&v,2)!=bytes) return NXT_FORMAT;
    v.vocab=hdr(&v,3);
    if(v.vocab!=151665||hdr(&v,4)!=151387||hdr(&v,9)!=22) return NXT_FORMAT;
    uint64_t sizes[]={8ull*v.vocab,1024,16ull*hdr(&v,4),12ull*hdr(&v,5),
        12ull*hdr(&v,6),0,12ull*hdr(&v,7),8ull*hdr(&v,8),0};
    for(unsigned i=0;i<9;i++) {
        uint32_t a=hdr(&v,10+i),b=i==8?(uint32_t)bytes:hdr(&v,11+i);
        if(a<128||a>b||b>bytes||a%4||sizes[i]>(uint64_t)b-a) return NXT_FORMAT;
    }
    /* Source table integrity is sealed by the loader/fixture SHA-256. Runtime
     * still bounds-checks every externally chosen ID, offset and decomposition. */
    *t=v; return 0;
}
static int scalar(const uint8_t *s,size_t n,uint32_t *cp,size_t *used) {
    if(!n) return NXT_UTF8;
    uint32_t c=s[0];unsigned count=c<0x80?1:c>=0xc2&&c<=0xdf?2:c>=0xe0&&c<=0xef?3:c>=0xf0&&c<=0xf4?4:0;
    if(!count||n<count) return NXT_UTF8;
    if(count>1) { c &= (1u<<(7-count))-1; for(unsigned i=1;i<count;i++) {if((s[i]&0xc0)!=0x80)return NXT_UTF8;c=(c<<6)|(s[i]&63);} }
    if((count==2&&c<128)||(count==3&&c<2048)||(count==4&&c<65536)||c>0x10ffff||(c>=0xd800&&c<=0xdfff)) return NXT_UTF8;
    *cp=c;*used=count;return 0;
}
static unsigned put_utf8(uint32_t c,uint8_t *s) {
    if(c<128) {s[0]=c;return 1;}
    unsigned n=c<2048?2:c<65536?3:4;for(unsigned i=n-1;i;i--){s[i]=0x80|(c&63);c>>=6;}s[0]=(0xff<<(8-n))|c;return n;
}
static int lookup(const uint8_t *p,uint32_t count,unsigned width,uint32_t key) {
    uint32_t lo=0,hi=count;while(lo<hi){uint32_t m=lo+(hi-lo)/2;if(word(p,m*width)<key)lo=m+1;else hi=m;}
    return lo<count&&word(p,lo*width)==key?(int)lo:-1;
}
static unsigned ccc(const nxt_tokenizer *t,uint32_t cp) {
    const uint8_t *p=table(t,7);int i=lookup(p,hdr(t,8),2,cp);return i<0?0:word(p,2*i+1);
}
static uint32_t compose(const nxt_tokenizer *t,uint32_t a,uint32_t b) {
    const uint8_t *p=table(t,6);uint32_t lo=0,hi=hdr(t,7);
    while(lo<hi){uint32_t m=lo+(hi-lo)/2,x=word(p,3*m),y=word(p,3*m+1);if(x<a||(x==a&&y<b))lo=m+1;else hi=m;}
    return lo<hdr(t,7)&&word(p,3*lo)==a&&word(p,3*lo+1)==b?word(p,3*lo+2):0;
}
static int normalize(const nxt_tokenizer *t,nxt_work *w,const uint8_t *s,size_t n,size_t *out) {
    size_t at=0,count=0;
    while(at<n) {
        uint32_t cp;size_t used;int rc=scalar(s+at,n-at,&cp,&used);if(rc)return rc;at+=used;
        const uint8_t *d=table(t,4);int idx=lookup(d,hdr(t,6),3,cp);uint32_t len=1,offset=0;
        if(idx>=0){offset=word(d,3*idx+1);len=word(d,3*idx+2);if((uint64_t)(offset+0ull+len)*4>hdr(t,16)-hdr(t,15))return NXT_FORMAT;}
        if(!len||len>NXT_NORMAL_MAX-count)return NXT_BOUNDS;
        for(uint32_t i=0;i<len;i++) {
            uint32_t c=idx<0?cp:word(table(t,5),offset+i);unsigned cl=ccc(t,c);size_t j=count++;
            while(cl&&j&&ccc(t,w->cp[j-1])>cl){w->cp[j]=w->cp[j-1];j--;}w->cp[j]=c;
        }
    }
    size_t write=0,starter=0;unsigned previous=0;
    for(size_t i=0;i<count;i++) {
        uint32_t c=w->cp[i];unsigned cl=ccc(t,c);uint32_t merged=write&&(previous<cl||previous==0)?compose(t,w->cp[starter],c):0;
        if(merged)w->cp[starter]=merged;
        else {if(!cl)starter=write;w->cp[write++]=c;previous=cl;}
    }
    size_t bytes=0;for(size_t i=0;i<write;i++){uint8_t tmp[4];unsigned len=put_utf8(w->cp[i],tmp);if(len>NXT_NORMAL_MAX-bytes)return NXT_BOUNDS;memcpy(w->normalized+bytes,tmp,len);bytes+=len;}
    *out=bytes;return 0;
}
static unsigned category(const nxt_tokenizer *t,uint32_t cp) {
    const uint8_t *p=table(t,3);uint32_t lo=0,hi=hdr(t,5);
    while(lo<hi){uint32_t m=lo+(hi-lo)/2;if(word(p,3*m+1)<cp)lo=m+1;else hi=m;}
    return lo<hdr(t,5)&&word(p,3*lo)<=cp?word(p,3*lo+2):0;
}
static unsigned at_category(const nxt_tokenizer *t,const uint8_t *s,size_t n,size_t at,size_t *next) {
    uint32_t cp;size_t used;if(at>=n){*next=n;return 0;}if(scalar(s+at,n-at,&cp,&used)){*next=n;return 0;}*next=at+used;return category(t,cp);
}
static int lower(int c){return c>='A'&&c<='Z'?c+32:c;}
static size_t piece(const nxt_tokenizer *t,const uint8_t *s,size_t n) {
    if(s[0]=='\''&&n>1) {
        int c=lower(s[1]);if(c=='s'||c=='t'||c=='m'||c=='d')return 2;
        if(n>2&&((c=='r'&&lower(s[2])=='e')||(c=='v'&&lower(s[2])=='e')||(c=='l'&&lower(s[2])=='l')))return 3;
    }
    size_t next,at=0;unsigned cat=at_category(t,s,n,0,&next);
    if(cat&1)at=next;
    else if(!(cat&(8|1|2))&&next<n){size_t end;if(at_category(t,s,n,next,&end)&1)at=end;}
    if(at){while(at<n){size_t end;if(!(at_category(t,s,n,at,&end)&1))break;at=end;}return at;}
    if(cat&2)return next;
    at=s[0]==' '?1:0;size_t begin=at;
    while(at<n){size_t end;unsigned c=at_category(t,s,n,at,&end);if(c&(4|1|2))break;at=end;}
    if(at>begin){while(at<n&&(s[at]=='\r'||s[at]=='\n'))at++;return at;}
    at=0;size_t last_newline=0,last_start=0;
    while(at<n){size_t end;unsigned c=at_category(t,s,n,at,&end);if(!(c&4))break;last_start=at;at=end;if(c&8)last_newline=at;}
    if(last_newline)return last_newline;
    if(at)return at<n&&last_start?last_start:at;
    return next;
}
static uint32_t pair_rank(const nxt_tokenizer *t,uint32_t a,uint32_t b,uint32_t *merged) {
    const uint8_t *p=table(t,2);uint32_t lo=0,hi=hdr(t,4);
    while(lo<hi){uint32_t m=lo+(hi-lo)/2,x=word(p,4*m),y=word(p,4*m+1);if(x<a||(x==a&&y<b))lo=m+1;else hi=m;}
    if(lo==hdr(t,4)||word(p,4*lo)!=a||word(p,4*lo+1)!=b)return UINT32_MAX;
    *merged=word(p,4*lo+3);return word(p,4*lo+2);
}
static int token_bytes(const nxt_tokenizer *t,uint32_t id,const uint8_t **text,uint32_t *len,unsigned *flags) {
    if(id>=t->vocab)return NXT_ARGUMENT;const uint8_t *p=table(t,0);
    uint32_t off=word(p,id*2),sz=word(p,id*2+1);*len=sz&0xffffff;*flags=sz>>24;
    if(!*len||off>t->bytes-hdr(t,18)||*len>t->bytes-hdr(t,18)-off)return NXT_FORMAT;
    *text=table(t,8)+off;return 0;
}
static uint32_t added(const nxt_tokenizer *t,const uint8_t *s,size_t n,size_t *used) {
    if(!n||s[0]!='<')return UINT32_MAX;
    for(uint32_t id=151643;id<t->vocab;id++) {const uint8_t *v;uint32_t len;unsigned f;if(token_bytes(t,id,&v,&len,&f))continue;if(len<=n&&!memcmp(s,v,len)){*used=len;return id;}}
    return UINT32_MAX;
}
int nxt_encode(const nxt_tokenizer *t,nxt_work *w,const char *text,size_t n,uint32_t *out,size_t cap,size_t *count) {
    if(!t||!w||!text||!out||!count)return NXT_ARGUMENT;
    if(n>NXT_TEXT_MAX)return NXT_BOUNDS;
    size_t size;int rc=normalize(t,w,(const uint8_t *)text,n,&size);if(rc)return rc;
    size_t at=0,total=0,until=0;
    while(at<size){
        size_t used=0;uint32_t special=added(t,w->normalized+at,size-at,&used);
        if(special!=UINT32_MAX){if(total>=NXT_NORMAL_MAX)return NXT_BOUNDS;w->ids[total++]=special;at+=used;continue;}
        if(at>=until){until=at+1;for(;until<size;until++){size_t dummy;if(added(t,w->normalized+until,size-until,&dummy)!=UINT32_MAX)break;}}
        size_t len=piece(t,w->normalized+at,until-at);
        if(!len||len>NXT_NORMAL_MAX-total)return NXT_BOUNDS;
        for(size_t i=0;i<len;i++)w->ids[total+i]=word(table(t,1),w->normalized[at+i]);
        size_t live=len;
        while(live>1){uint32_t rank=UINT32_MAX,best_token=0;size_t best=0;
            for(size_t i=0;i+1<live;i++){uint32_t m=0,r=pair_rank(t,w->ids[total+i],w->ids[total+i+1],&m);if(r<rank){rank=r;best=i;best_token=m;}}
            if(rank==UINT32_MAX)break;
            w->ids[total+best]=best_token;memmove(w->ids+total+best+1,w->ids+total+best+2,(live-best-2)*4);live--;
        }
        total+=live;at+=len;
    }
    if(total>cap)return NXT_BOUNDS;
    memcpy(out,w->ids,total*4);*count=total;return 0;
}
static int append(char *out,size_t cap,size_t *n,const char *s,size_t len) {
    if(*n>cap||len>cap-*n)return NXT_BOUNDS;if(out)memcpy(out+*n,s,len);*n+=len;return 0;
}
static const char initial[]="<|im_start|>system\nYou are Qwen, created by Alibaba Cloud. You are a helpful assistant.<|im_end|>\n";
const char *nxt_system_prefix(size_t *bytes){if(bytes)*bytes=sizeof(initial)-1;return initial;}
int nxt_template(const nxt_message *messages,size_t count,int prompt,char *out,size_t cap,size_t *length) {
    if(!messages||!count||count>32||!out||!length||(prompt!=0&&prompt!=1))return NXT_ARGUMENT;
    size_t need=0;
    for(int pass=0;pass<2;pass++){need=0;char *dst=pass?out:0;
        if(!messages[0].role)return NXT_ARGUMENT;
        if(strcmp(messages[0].role,"system")&&append(dst,cap,&need,initial,sizeof(initial)-1))return NXT_BOUNDS;
        for(size_t i=0;i<count;i++){
            const nxt_message *m=&messages[i];
            if(!m->role||!m->text||(strcmp(m->role,"system")&&strcmp(m->role,"user")&&strcmp(m->role,"assistant")))return NXT_ARGUMENT;
            if(m->length>NXT_TEXT_MAX)return NXT_BOUNDS;
            if(append(dst,cap,&need,"<|im_start|>",12)||append(dst,cap,&need,m->role,strlen(m->role))||
               append(dst,cap,&need,"\n",1)||append(dst,cap,&need,m->text,m->length)||append(dst,cap,&need,"<|im_end|>\n",11))return NXT_BOUNDS;
        }
        if(prompt&&append(dst,cap,&need,"<|im_start|>assistant\n",22))return NXT_BOUNDS;
        if(need>NXT_TEXT_MAX)return NXT_BOUNDS;
    }
    *length=need;return 0;
}
static int emit_byte(nxt_decoder *d,uint8_t b,char *out,size_t cap,size_t *count) {
    if(!d->count&&b<128){return append(out,cap,count,(const char *)&b,1);}
    if(!d->count){if(b>=0xc2&&b<=0xf4){d->pending[d->count++]=b;return 0;}return append(out,cap,count,"\xef\xbf\xbd",3);}
    uint8_t first=d->pending[0];unsigned want=first<0xe0?2:first<0xf0?3:4;
    int valid=(b&0xc0)==0x80;
    if(d->count==1)valid &= !(first==0xe0&&b<0xa0)&&!(first==0xed&&b>=0xa0)&&!(first==0xf0&&b<0x90)&&!(first==0xf4&&b>=0x90);
    if(!valid){d->count=0;int rc=append(out,cap,count,"\xef\xbf\xbd",3);return rc?rc:emit_byte(d,b,out,cap,count);}
    d->pending[d->count++]=b;
    if(d->count==want){int rc=append(out,cap,count,(const char *)d->pending,want);d->count=0;return rc;}return 0;
}
int nxt_decode(const nxt_tokenizer *t,nxt_decoder *decoder,uint32_t id,int skip,int final,char *out,size_t cap,size_t *length) {
    if(!t||!decoder||!out||!length||decoder->count>3)return NXT_ARGUMENT;
    const uint8_t *s=0;uint32_t n=0;unsigned f=0;
    if(id!=UINT32_MAX){
        if(id>=151936)return NXT_ARGUMENT;
        if(id<t->vocab){int rc=token_bytes(t,id,&s,&n,&f);if(rc)return rc;}
        /* Padded model vocabulary has no decoded bytes, like the original
         * tokenizer. IDs beyond the model's vocabulary remain invalid. */
    }
    for(int pass=0;pass<2;pass++){
        nxt_decoder d=*decoder;size_t written=0;
        if(!(skip&&f==2))for(uint32_t i=0;i<n;i++){int rc=emit_byte(&d,s[i],pass?out:0,cap,&written);if(rc)return rc;}
        if(final&&d.count){int rc=append(pass?out:0,cap,&written,"\xef\xbf\xbd",3);if(rc)return rc;d.count=0;}
        if(pass){*decoder=d;*length=written;}
    }
    return 0;
}
