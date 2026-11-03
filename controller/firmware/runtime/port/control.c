#include "control.h"
#include <string.h>
int nxc_parse_cancel(const char *line,uint64_t *target){
    if(!line||!target||strlen(line)!=24||memcmp(line,":cancel ",8))return 0;
    uint64_t value=0;
    for(unsigned i=8;i<24;i++){
        unsigned c=(unsigned char)line[i],digit;
        if(c>='0'&&c<='9')digit=c-'0';
        else if(c>='a'&&c<='f')digit=c-'a'+10;
        else return 0;
        value=(value<<4)|digit;
    }
    if(!value)return 0;*target=value;return 1;
}
int nxc_feed(nxc_control *state,unsigned char c,uint64_t session,uint64_t *target){
    if(!state||!target)return NXC_REJECTED;
    if(c=='\r')return NXC_NONE;
    if(c=='\n'){
        state->line[state->used]=0;uint64_t value=0;
        int valid=!state->overflow&&nxc_parse_cancel(state->line,&value);
        state->used=state->overflow=0;*target=value;
        return valid?(value==session?NXC_CANCEL:NXC_STALE):NXC_REJECTED;
    }
    if(c<32||c>126)state->overflow=1;
    else if(state->used<sizeof(state->line)-1)state->line[state->used++]=(char)c;
    else state->overflow=1;
    return NXC_NONE;
}
