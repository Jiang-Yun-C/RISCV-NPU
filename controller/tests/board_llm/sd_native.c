#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <sys/mman.h>
#include <unistd.h>
#include <fcntl.h>
#include "sd_native_port.h"
#include "loader.h"
#include "sha256.h"
#include "trusted.h"
uint32_t nx_sd_test_regs[64];
static int image;
static uint32_t fault_address,sector_fault,sealed,entered,count;
static uint64_t written,blocks;
uint32_t nx_sd_test_ticks(void){return 0;}
int nx_sd_test_initialize(void){return 0;}
int nx_sd_test_sector(uint32_t lba,uint8_t *out){
    blocks++;
    if(lba==sector_fault)return E_CRC;
    return pread(image,out,512,(off_t)lba*512)==512?0:E_CARD;
}
void nx_sd_test_after_store(uint32_t address,unsigned n){
    written+=n;
    if(fault_address>=address&&(uint64_t)fault_address<((uint64_t)address+n))
        *(volatile uint8_t *)(uintptr_t)fault_address^=1;
}
int nx_sd_test_finish(uint32_t pc,uint32_t entries){
    sealed=1;entered=pc;count=entries;return 0;
}
static uint32_t u32(const uint8_t *p){return (uint32_t)p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;}
static int same(const uint8_t *a,const uint8_t *b){for(int i=0;i<32;i++)if(a[i]!=b[i])return 0;return 1;}
int main(int argc,char **argv){
    if(argc!=5)return 90;
    image=open(argv[1],O_RDONLY);if(image<0)return 91;
    fault_address=(uint32_t)strtoul(argv[3],0,0);sector_fault=(uint32_t)strtoul(argv[4],0,0);
    void *mem=mmap((void *)0x80000000,0x40000000,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED_NOREPLACE,-1,0);
    if(mem!=(void *)0x80000000)return 92;
    nx_sd_test_regs[0x34/4]=1;
    uint32_t rc=nx_sd_boot(),verified=0;int app_ok=0;uint8_t digest[32];nx_sha h;
    if(entered){
        nx_sha_init(&h);nx_sha_add(&h,(const uint8_t *)0xb4000000,(unsigned)strtoul(argv[2],0,10));nx_sha_end(&h,digest);
        app_ok=same(digest,nx_trusted_apps[0]);
        for(unsigned i=0;i<count;i++){
            const uint8_t *e=(const uint8_t *)(uintptr_t)(NX_DIRECTORY+i*256);
            uint32_t address=(u32(e+176)==1?0x80000000u:0xb8000000u)+u32(e+184);
            nx_sha_init(&h);nx_sha_add(&h,(const uint8_t *)(uintptr_t)address,u32(e+168));nx_sha_end(&h,digest);
            verified+=same(digest,e+192);
        }
    }
    printf("{\"error\":%u,\"sealed\":%u,\"entry\":%u,\"entries\":%u,\"verified_memory_spans\":%u,\"app_memory_matches\":%d,\"written_bytes\":%llu,\"blocks\":%llu}\n",rc,sealed,entered,count,verified,app_ok,(unsigned long long)written,(unsigned long long)blocks);
    close(image);munmap(mem,0x40000000);return 0;
}
