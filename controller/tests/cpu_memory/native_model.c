/* Actual production main/model/runtime/tokenizer/stream, with the established
 * two-layer NX_OPT13_TEST fixture. Emit full valid logits/KV bytes for a direct
 * old/new comparison, not only a checksum. Board I/O and time are substitutes. */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <setjmp.h>
#include <sys/mman.h>
#define main t25_service_main
#include NX_PRODUCTION_MAIN
#undef main

static jmp_buf fixture_exit;
static uint64_t fixture_ticks;
static unsigned fixture_commands,fixture_stack_failure;
static FILE *numeric_dump;
uint64_t nx_t25_test_ticks(void){return ++fixture_ticks;}
void nx_t25_test_put(char ch){fputc((unsigned char)ch,stdout);fixture_ticks++;}
int nx_t25_test_stack_peak(uint32_t *peak){
    *peak=1024;return fixture_stack_failure?NXR_FAULT:0;
}
static void save_bytes(const void *ptr,size_t bytes){
    if(fwrite(ptr,1,bytes,numeric_dump)!=bytes){perror("numeric dump");exit(2);}
}
static void snapshot(void){
    if(!fixture_commands)return;
    const float *logits=request.state==NXR_STOPPED?nx_logits_v2(binding.session):NULL;
    uint32_t header[5]={request.state,request.generated,request.stop,
                        request.kv_length,logits!=NULL};
    save_bytes(header,sizeof(header));
    if(request.state==NXR_STOPPED){
        save_bytes(request.output,(size_t)request.generated*sizeof(request.output[0]));
        if(logits)save_bytes(logits,32*sizeof(float));
        for(unsigned layer=0;layer<2;layer++)for(unsigned value=0;value<2;value++)
            save_bytes(nx_cache(binding.session,layer,value),
                       (size_t)nx_length(binding.session)*4*sizeof(float));
    }
}
int nx_t25_test_read_line(char *buffer,size_t capacity){
    snapshot();
    if(!fgets(buffer,(int)capacity,stdin))longjmp(fixture_exit,1);
    size_t size=strlen(buffer);
    if(size&&buffer[size-1]=='\n')buffer[--size]=0;
    if(size&&buffer[size-1]=='\r')buffer[--size]=0;
    fixture_commands++;return (int)size;
}
static void map_region(uintptr_t address,size_t bytes){
    void *p=mmap((void *)address,bytes,PROT_READ|PROT_WRITE,
                MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED_NOREPLACE,-1,0);
    if(p==MAP_FAILED){perror("test mmap");exit(2);}
}
int main(int argc,char **argv){
    if(argc<2||argc>3)return 2;
    numeric_dump=fopen(argv[1],"wb");if(!numeric_dump){perror("dump open");return 2;}
    fixture_stack_failure=argc==3&&strcmp(argv[2],"stack-failure")==0;
    map_region(0x10000000u,4096);
    map_region(0xa8000000u,15728640);
    map_region(0xac000000u,2*1024*1024);
    map_region(0xba080000u,4096);
    *(volatile uint32_t *)0x100000e0u=2;
    if(!setjmp(fixture_exit))t25_service_main();
    if(fclose(numeric_dump)){perror("dump close");return 2;}
    return 0;
}
