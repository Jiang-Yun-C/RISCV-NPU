#include "protocol.h"
#define REG(o) (*(volatile uint32_t *)(uintptr_t)(0x10000000u+(o)))
static uint8_t packet[28+NX_CHUNK_MAX+4];
static uint32_t base,size,entry,image_crc,received,next_sequence,last_crc,last_sequence;
static int active;
static uint32_t ticks(void) { uint32_t t; __asm__ volatile("csrr %0,mcycle":"=r"(t)); return t; }
static void put(uint8_t c) { while(REG(4)&1u) {} REG(0)=c; }
static void text(const char *s) { while(*s)put((uint8_t)*s++); }
static int get(uint8_t *v) {
    uint32_t start=ticks();
    do { if(REG(4)&2u) { *v=(uint8_t)REG(8); return 1; } } while(ticks()-start<NX_BYTE_TIMEOUT);
    return 0;
}
static uint32_t word(const uint8_t *p) {
    return (uint32_t)p[0]|((uint32_t)p[1]<<8)|((uint32_t)p[2]<<16)|((uint32_t)p[3]<<24);
}
static void response(uint32_t sequence,uint32_t status) {
    uint32_t words[]={0x4b41584eu,sequence,status,next_sequence};
    uint32_t crc=~0u;
    for(unsigned i=0;i<16;i++) { uint8_t v=(uint8_t)(words[i/4]>>(8*(i%4))); put(v); crc=nx_crc_byte(crc,v); }
    crc=~crc;
    for(unsigned i=0;i<4;i++)put((uint8_t)(crc>>(8*i)));
}
static void visible(void) {
    /* T09 write-through D cache: drain writes, invalidate D tags, invalidate I
       cache and serialize fetch. Ordinary FENCE alone cannot remove stale I. */
    __asm__ volatile("fence iorw,iorw" ::: "memory");
    __asm__ volatile(".word 0x0000500f" ::: "memory");
#ifndef NX_OMIT_FENCE_I
    __asm__ volatile("fence.i" ::: "memory");
#endif
}
static void launch(void) { visible(); ((void (*)(void))(uintptr_t)entry)(); }
int main(void) {
    uint32_t mode=REG(0x10);
    REG(0x30)=mode;
    if(mode==1) {
        base=NX_APP_BASE;size=REG(0x14);entry=NX_APP_BASE;
        if(!nx_image_range(base,size,entry))return 1;
        text("BOOT PRELOAD\n");launch();text("BOOT RETURN\n");
    } else text("BOOT PROTOCOL_BOOT\n");
    for(;;) {
        unsigned magic=0;uint8_t v;
        const uint8_t prefix[]={ 'N','X','U','1' };
        while(magic<4) {
            if(!get(&v)) { if(magic){active=0;next_sequence=0;response(0,NX_TIMEOUT);magic=0;} continue; }
            if(v==prefix[magic])packet[magic++]=v;
            else magic=(v=='N')?1u:0u;
        }
        unsigned pos=4,total=28;int timed_out=0;
        while(pos<total) { if(!get(&packet[pos++])) {timed_out=1;break;} }
        if(timed_out) { active=0;next_sequence=0;response(0,NX_TIMEOUT);continue; }
        uint32_t command=word(packet+4),sequence=word(packet+8),address=word(packet+12);
        uint32_t length=word(packet+16),target=word(packet+20),expected_crc=word(packet+24);
        if(command==NX_DATA && length>NX_CHUNK_MAX) { active=0;next_sequence=0;response(sequence,NX_FORMAT);continue; }
        total+=command==NX_DATA?length:0; total+=4;
        while(pos<total) { if(!get(&packet[pos++])) {timed_out=1;break;} }
        if(timed_out) { active=0;next_sequence=0;response(sequence,NX_TIMEOUT);continue; }
        uint32_t crc=~0u;
        for(unsigned i=0;i<total-4;i++)crc=nx_crc_byte(crc,packet[i]);
        crc=~crc;
        if(crc!=word(packet+total-4)) {response(sequence,NX_CRC);continue;}
        uint32_t status=NX_OK;
        if(command==NX_BEGIN) {
            if(sequence!=0)status=NX_SEQUENCE;
            else if(!nx_image_range(address,length,target))status=NX_RANGE;
            else {base=address;size=length;entry=target;image_crc=expected_crc;received=0;next_sequence=1;active=1;last_sequence=0;}
        } else if(command==NX_DATA) {
            if(!active)status=NX_INCOMPLETE;
            else if(sequence==last_sequence && crc==last_crc && last_sequence)status=NX_DUP;
            else if(sequence!=next_sequence)status=NX_SEQUENCE;
            else if(!length || address!=base+received || length>size-received || target || expected_crc)status=NX_RANGE;
            else {
                for(unsigned i=0;i<length;i++)*(volatile uint8_t *)(uintptr_t)(address+i)=packet[28+i];
                received+=length;last_crc=crc;last_sequence=sequence;next_sequence++;
            }
        } else if(command==NX_RUN) {
            if(!active || received!=size)status=NX_INCOMPLETE;
            else if(sequence!=next_sequence)status=NX_SEQUENCE;
            else if(address!=base || length!=size || target!=entry || expected_crc!=image_crc)status=NX_RANGE;
            else {
                visible();uint32_t actual=~0u;
                for(unsigned i=0;i<size;i++)actual=nx_crc_byte(actual,*(volatile uint8_t *)(uintptr_t)(base+i));
                if(~actual!=image_crc)status=NX_IMAGE_CRC;
            }
        } else status=NX_FORMAT;
        response(sequence,status);
        if(command==NX_RUN && status==NX_OK) { active=0;launch();text("BOOT RETURN\n"); }
    }
}
