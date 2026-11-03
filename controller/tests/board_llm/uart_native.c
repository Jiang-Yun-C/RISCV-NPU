#define _POSIX_C_SOURCE 200809L
#define _GNU_SOURCE
#include <poll.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>
#include "stream.h"
#include "sha256.h"
#include "trusted.h"
static unsigned sealed,entered,entries;
static int32_t dot;
static uint64_t ticks(void *cookie){(void)cookie;struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return (uint64_t)t.tv_sec*1000000000+t.tv_nsec;}
static int get(void *cookie,uint64_t deadline,uint8_t *out){
    (void)cookie;static uint8_t buffer[1024];static unsigned used,size;
    while(used==size){
        struct pollfd fd={.fd=0,.events=POLLIN};
        if(poll(&fd,1,20)>0){ssize_t n=read(0,buffer,sizeof(buffer));if(n<=0)return -1;size=(unsigned)n;used=0;break;}
        if(deadline&&ticks(0)>=deadline)return 0;
    }
    *out=buffer[used++];return 1;
}
static void put(void *cookie,const uint8_t *p,unsigned n){(void)cookie;while(n){ssize_t sent=write(1,p,n);if(sent<=0)exit(90);p+=sent;n-=(unsigned)sent;}}
static int seal(void *cookie){(void)cookie;sealed++;return 0;}
static void reset(void *cookie){(void)cookie;exit(91);}
void nx_uart_observe_model(int32_t d,uint32_t n){dot=d;entries=n;}
void nx_uart_enter(uint32_t address){entered=address;}
static uint32_t u32(const uint8_t *p){return (uint32_t)p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;}
static int same(const uint8_t *a,const uint8_t *b,unsigned n){while(n--)if(*a++!=*b++)return 0;return 1;}
int main(int argc,char **argv){
    if(argc!=2)return 93;
    void *memory=mmap((void *)0x80000000,0x40000000,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED_NOREPLACE,-1,0);
    if(memory!=(void *)0x80000000)return 94;
    nx_uart_io io={.get=get,.put=put,.ticks=ticks,.seal=seal,.reset=reset,.frame_ticks=1000000000};nx_uart_init(&io);
    uint32_t rc=nx_uart_boot();if(rc)nx_uart_reject(rc);
    unsigned verified=0;nx_sha hash;uint8_t digest[32];int app_ok=0;
    if(entered){
        nx_sha_init(&hash);nx_sha_add(&hash,(const uint8_t *)0xb4000000,(unsigned)strtoul(argv[1],0,10));nx_sha_end(&hash,digest);
        app_ok=same(digest,nx_trusted_apps[0],32);
        for(unsigned i=0;i<entries;i++){
            const uint8_t *e=(const uint8_t *)(uintptr_t)(0xba000000+256*i);
            uint32_t address=(u32(e+176)==1?0x80000000u:0xb8000000u)+u32(e+184);
            nx_sha_init(&hash);nx_sha_add(&hash,(const uint8_t *)(uintptr_t)address,u32(e+168));nx_sha_end(&hash,digest);
            verified+=same(digest,e+192,32);
        }
    }
    fprintf(stderr,"{\"error\":%u,\"sealed\":%u,\"entry\":%u,\"entries\":%u,\"verified_memory_spans\":%u,\"app_memory_matches\":%d,\"dot\":%d}\n",rc,sealed,entered,entries,verified,app_ok,dot);
    munmap(memory,0x40000000);return 0;
}
