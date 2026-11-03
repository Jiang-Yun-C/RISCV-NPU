#include "application.h"
#include <string.h>
#include <limits.h>

struct parser { const char *s; size_t n,pos; struct app_program *p; };
static void space(struct parser *p) { while(p->pos<p->n && strchr(" \t\r\n",p->s[p->pos]))p->pos++; }
static int hex(char c) { return c>='0'&&c<='9'?c-'0':c>='a'&&c<='f'?c-'a'+10:c>='A'&&c<='F'?c-'A'+10:-1; }
static int value(struct parser *p,int depth) {
    space(p);if(depth>16||p->pos==p->n||p->p->used==256)return -1;
    int i=p->p->used++;struct app_token *t=&p->p->tokens[i];t->child=-1;
    char c=p->s[p->pos++];
    if(c=='[') {
        t->kind=1;space(p);int previous=-1;
        if(p->pos<p->n&&p->s[p->pos]==']'){p->pos++;t->next=p->p->used;return i;}
        for(;;){int child=value(p,depth+1);if(child<0)return -1;
            if(previous<0)t->child=child;previous=child;t->count++;space(p);
            if(p->pos==p->n)return -1;c=p->s[p->pos++];if(c==']')break;if(c!=',')return -1;
        }
    } else if(c=='"') {
        t->kind=2;int len=0,done=0;
        while(p->pos<p->n){unsigned char x=(unsigned char)p->s[p->pos++];
            if(x=='"'){done=1;break;}if(x<32)return -1;
            if(x=='\\') {if(p->pos==p->n)return -1;x=(unsigned char)p->s[p->pos++];
                if(x=='u'){int v=0;for(int k=0;k<4;k++){if(p->pos==p->n)return -1;int h=hex(p->s[p->pos++]);if(h<0)return -1;v=v*16+h;}if(v==0||v>127)return -1;x=(unsigned char)v;}
                else if(x=='b')x=8;else if(x=='f')x=12;else if(x=='n')x=10;else if(x=='r')x=13;else if(x=='t')x=9;
                else if(x!='"'&&x!='\\'&&x!='/')return -1;
            }
            if(len==23)return -1;t->string[len++]=(char)x;
        }if(!done)return -1;t->string[len]=0;
    } else {
        t->kind=3;int negative=c=='-';if(negative){if(p->pos==p->n)return -1;c=p->s[p->pos++];}
        if(c<'0'||c>'9')return -1;uint32_t v=(uint32_t)(c-'0');
        if(c=='0'&&p->pos<p->n&&p->s[p->pos]>='0'&&p->s[p->pos]<='9')return -1;
        while(p->pos<p->n&&p->s[p->pos]>='0'&&p->s[p->pos]<='9'){
            uint32_t digit=(uint32_t)(p->s[p->pos++]-'0');if(v>(INT_MAX-digit)/10u)return -1;v=v*10+digit;
        }t->number=negative?-(int32_t)v:(int32_t)v;
    }t->next=p->p->used;return i;
}
static int at(const struct app_program *p,int i,int k) { i=p->tokens[i].child;while(k--&&i>=0)i=p->tokens[i].next;return i; }
static int str(const struct app_program *p,int i,const char *s) { return i>=0&&p->tokens[i].kind==2&&!strcmp(p->tokens[i].string,s); }
static int sensor(const struct app_program *p,int i) { return str(p,i,"temperature")?1:str(p,i,"light")?2:0; }
static int validate(const struct app_program *p,int i,int depth,int *budget) {
    const struct app_token *a=&p->tokens[i];if(depth>2||a->kind!=1||a->count>8)return APP_FORMAT;
    for(int j=a->child;j<a->next&&j>=0;j=p->tokens[j].next){
        const struct app_token *n=&p->tokens[j];if(--*budget<0||n->kind!=1||n->count==0)return APP_FORMAT;
        int op=at(p,j,0),arg=at(p,j,1);
        if(str(p,op,"led")||str(p,op,"pwm")) {
            if(n->count!=2||p->tokens[arg].kind!=3)return APP_FORMAT;
            if(p->tokens[arg].number<0||p->tokens[arg].number>(str(p,op,"led")?1:100))return APP_RANGE;
        }else if(str(p,op,"read")) {
            if(n->count!=2||p->tokens[arg].kind!=2)return APP_FORMAT;if(!sensor(p,arg))return APP_UNSUPPORTED;
        }else if(str(p,op,"reject")) {
            if(n->count!=2||!str(p,arg,"UNSUPPORTED"))return APP_FORMAT;return APP_UNSUPPORTED;
        }else if(str(p,op,"if")) {
            if(n->count!=6)return APP_FORMAT;
            int cmp=at(p,j,2),threshold=at(p,j,3);
            if(p->tokens[arg].kind!=2||p->tokens[cmp].kind!=2)return APP_FORMAT;
            if(!sensor(p,arg))return APP_UNSUPPORTED;
            if(!(str(p,cmp,">")||str(p,cmp,"<")||str(p,cmp,">=")||str(p,cmp,"<="))||p->tokens[threshold].kind!=3||p->tokens[threshold].number < -100000||p->tokens[threshold].number>100000)return APP_FORMAT;
            int rc=validate(p,at(p,j,4),depth+1,budget);if(rc)return rc;rc=validate(p,at(p,j,5),depth+1,budget);if(rc)return rc;
        }else return APP_FORMAT;
    }return APP_OK;
}
int app_parse(struct app_program *p,const char *s,size_t n) {
    if(!p||!s||n>APP_TEXT_MAX||memchr(s,0,n))return APP_FORMAT;
    memset(p,0,sizeof(*p));struct parser ps={s,n,0,p};int root=value(&ps,0);space(&ps);
    if(root<0||ps.pos!=n)return APP_FORMAT;p->root=root;int budget=32;return validate(p,root,0,&budget);
}
static int visit(const struct app_program *p,int i,const struct app_state *s,struct app_result *r) {
    for(int j=p->tokens[i].child;j<p->tokens[i].next&&j>=0;j=p->tokens[j].next){
        int op=at(p,j,0),arg=at(p,j,1);
        if(str(p,op,"led")||str(p,op,"pwm")){
            uint32_t device=str(p,op,"pwm"),v=(uint32_t)p->tokens[arg].number;
            for(uint32_t k=0;k<r->count;k++)if(r->actions[k].device==device&&r->actions[k].value==v)return APP_DUPLICATE;
            if(r->count==8)return APP_FORMAT;r->actions[r->count++]=(struct app_action){device,v};
        }else if(str(p,op,"read"))r->read_mask|=(uint32_t)sensor(p,arg);
        else {int cmp=at(p,j,2);int32_t x=sensor(p,arg)==1?s->temperature:(int32_t)s->light,y=p->tokens[at(p,j,3)].number;
            int yes=str(p,cmp,">")?x>y:str(p,cmp,"<")?x<y:str(p,cmp,">=")?x>=y:x<=y;
            int rc=visit(p,at(p,j,yes?4:5),s,r);if(rc)return rc;
        }
    }return APP_OK;
}
int app_evaluate(const struct app_program *p,const struct app_state *s,uint32_t epoch,uint32_t now,struct app_result *r) {
    memset(r,0,sizeof(*r));if(s->temperature < -40||s->temperature>125||s->light>100000||s->epoch!=epoch)return APP_STATE;
    if((uint32_t)(now-s->sampled_at)>APP_TTL_CYCLES)return APP_STALE;
    struct app_result pending={0};int rc=visit(p,p->root,s,&pending);if(!rc)*r=pending;return rc;
}
const char *app_status_name(int s) { static const char *names[]={"OK","FORMAT","RANGE","UNSUPPORTED","STATE","STALE","NACK","TIMEOUT","DUPLICATE","REQUEST_ID"};return s>=0&&s<10?names[s]:"FORMAT"; }
uint32_t app_fingerprint(const char *s,size_t n) { uint32_t h=2166136261u;for(size_t i=0;i<n;i++){h^=(unsigned char)s[i];h*=16777619u;}return h; }
