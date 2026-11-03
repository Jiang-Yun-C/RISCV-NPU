/* Autonomous single-owner transport. Weights stay in external memory, while
 * Aq/Sa and a bounded staging buffer reside in DTCM. Arithmetic is a T14
 * transport workload; installed numerical capabilities remain zero until T15. */
#include "stream.h"
#include <stddef.h>
#include <riscv_vector.h>

volatile struct nx_stream_request request __attribute__((section(".request")));
volatile struct nx_stream_result result __attribute__((section(".result")));
static int8_t activation[4*4864] __attribute__((aligned(16)));
static float activation_scale[4*76] __attribute__((aligned(16)));
static uint8_t scratch[NX_STREAM_CHUNK] __attribute__((aligned(16)));

static uint64_t tick(void) {
    uint32_t a,b,c;
    do { __asm__ volatile("csrr %0, 0xb80" : "=r"(a));
         __asm__ volatile("csrr %0, 0xb00" : "=r"(b));
         __asm__ volatile("csrr %0, 0xb80" : "=r"(c)); } while(a!=c);
    return ((uint64_t)a<<32)|b;
}
static uint32_t span(uint32_t rows,uint32_t stride,uint32_t width) {
    if(!rows || !width || stride<width || rows-1>(UINT32_MAX-width)/stride) return 0;
    return (rows-1)*stride+width;
}
static int region(uint32_t a,uint32_t bytes,int write) {
    if(!bytes || bytes>UINT32_MAX-a) return 0;
    uint32_t end=a+bytes;
    if(!write && a>=0x80000000u && end<=0xa8000000u) return 1;
    if(a>=0xa8000000u && end<=0xac000000u) return 2;
    if(a>=0xac000000u && end<=0xb4000000u) return 3;
    if(a>=0xba000000u && end<=0xbc000000u) return 4;
    return 0;
}
static int overlap(uint32_t a,uint32_t an,uint32_t b,uint32_t bn) {
    return a<b+bn && b<a+an;
}
static int validate(void) {
    if(request.abi!=NX_STREAM_ABI || request.size!=sizeof(request)) return -2;
    if(!(request.session_lo|request.session_hi) || !(request.sequence_lo|request.sequence_hi)) return -10;
    for(unsigned i=0;i<4;i++) if(request.reserved[i]) return -1;
    if(!request.n) return -1;
    uint32_t in=0,out=0;
    if(request.opcode==NX_STREAM_COPY) {
        if(request.m || request.k || request.scales || request.bias || request.aq || request.sa || request.output_stride) return -1;
        in=span(request.n,request.source_stride,request.row_bytes);
        out=span(request.n,request.destination_stride,request.row_bytes);
        if(!in||!out) return -4;
        if((request.source_stride|request.destination_stride)&15) return -5;
    } else if(request.opcode==NX_STREAM_LINEAR) {
        if(request.m!=1 && request.m!=4) return -3;
        if(request.k!=896 && request.k!=4864) return -3;
        if(request.n>151936 || request.row_bytes || request.source_stride || request.destination_stride) return -1;
        in=span(request.n,request.k,request.k);
        out=span(request.m,request.output_stride,request.n*4);
        if(!in||!out) return -4;
        if(request.output_stride&3) return -5;
        uint32_t addresses[4]={request.scales,request.bias,request.aq,request.sa};
        uint32_t bytes[4]={request.n*(request.k/64)*4,request.n*4,request.m*request.k,request.m*(request.k/64)*4};
        for(unsigned i=0;i<4;i++) {
            if(i==1&&!addresses[i])continue;
            if(addresses[i]&15)return -5;
            if(!region(addresses[i],bytes[i],0) || overlap(request.destination,out,addresses[i],bytes[i]))return -4;
        }
    } else return -3;
    if((request.source|request.destination)&15) return -5;
    if(!region(request.source,in,0) || !region(request.destination,out,1) || overlap(request.source,in,request.destination,out)) return -4;
    return 0;
}
/* Split at BOTH 4KiB boundaries. vl handles byte tails without over-read or
 * unstrobed writes. One vector load/store group is in flight at a time. */
static void copy_bytes(uint8_t *dst,const uint8_t *src,uint32_t bytes,int external_dst) {
    while(bytes) {
        uint32_t count=bytes<NX_STREAM_CHUNK?bytes:NX_STREAM_CHUNK;
        uint32_t room=4096-((uintptr_t)src&4095);
        if(count>room)count=room;
        room=4096-((uintptr_t)dst&4095);if(count>room)count=room;
        uint64_t begin=tick();
        size_t vl=__riscv_vsetvl_e8m4(count);
        vuint8m4_t data=__riscv_vle8_v_u8m4(src,vl);
        __riscv_vse8_v_u8m4(scratch,data,vl);
        result.load_cycles+=tick()-begin;
        begin=tick();
        uint32_t sum=0;for(uint32_t i=0;i<count;i++) sum+=scratch[i];
        result.checksum+=sum;
        result.compute_cycles+=tick()-begin;
        begin=tick();
        data=__riscv_vle8_v_u8m4(scratch,vl);
        __riscv_vse8_v_u8m4(dst,data,vl);
        __asm__ volatile("fence rw,rw" ::: "memory");
        result.write_cycles+=tick()-begin;
        result.payload_read+=count;
        if(external_dst) result.payload_write+=count;
        src+=count;dst+=count;bytes-=count;
    }
}
int main(void) {
    uint64_t begin=tick();
    result.abi=NX_STREAM_ABI;result.size=sizeof(result);
    result.session_lo=request.session_lo;result.session_hi=request.session_hi;
    result.sequence_lo=request.sequence_lo;result.sequence_hi=request.sequence_hi;
    result.valid=0;result.tiles=0;result.rows=0;result.checksum=0;result.reserved=0;
    result.payload_read=0;result.payload_write=0;result.load_cycles=0;
    result.compute_cycles=0;result.write_cycles=0;result.other_cycles=0;
    result.status=validate();
    if(result.status)goto finish;
    if(request.opcode==NX_STREAM_LINEAR) {
        copy_bytes((uint8_t *)activation,(const uint8_t *)request.aq,request.m*request.k,0);
        copy_bytes((uint8_t *)activation_scale,(const uint8_t *)request.sa,request.m*(request.k/64)*4,0);
    }
    for(uint32_t base=0;base<request.n;base+=NX_STREAM_ROWS) {
        uint32_t end=request.n-base<NX_STREAM_ROWS?request.n:base+NX_STREAM_ROWS;
        for(uint32_t row=base;row<end;row++) {
            if(request.opcode==NX_STREAM_COPY) {
                copy_bytes((uint8_t *)(request.destination+row*request.destination_stride),
                    (const uint8_t *)(request.source+row*request.source_stride),request.row_bytes,1);
            } else {
                uint32_t groups=request.k/64;float sum[4]={0,0,0,0};
                for(uint32_t g=0;g<groups;g++) {
                    uint64_t t=tick();size_t vl=__riscv_vsetvl_e8m4(64);
                    vint8m4_t w=__riscv_vle8_v_i8m4((const int8_t *)(request.source+row*request.k+g*64),vl);
                    float sw=((const volatile float *)request.scales)[row*groups+g];
                    result.load_cycles+=tick()-t;result.payload_read+=68;
                    t=tick();
                    for(uint32_t token=0;token<request.m;token++) {
                        vint8m4_t a=__riscv_vle8_v_i8m4(activation+token*request.k+g*64,vl);
                        vint16m8_t p=__riscv_vwmul_vv_i16m8(a,w,vl);
                        vint32m1_t z=__riscv_vmv_v_x_i32m1(0,1);
                        vint32m1_t r=__riscv_vwredsum_vs_i16m8_i32m1(p,z,vl);
                        int32_t dot=__riscv_vmv_x_s_i32m1_i32(r);
                        float value=(float)dot;value=value*activation_scale[token*groups+g];
                        value=value*sw;sum[token]=sum[token]+value;
                    }
                    result.compute_cycles+=tick()-t;
                }
                float bias=0;
                if(request.bias) {uint64_t t=tick();bias=((const volatile float *)request.bias)[row];result.load_cycles+=tick()-t;result.payload_read+=4;}
                uint64_t t=tick();
                for(uint32_t token=0;token<request.m;token++) sum[token]=sum[token]+bias;
                result.compute_cycles+=tick()-t;t=tick();
                for(uint32_t token=0;token<request.m;token++)
                    *(volatile float *)(request.destination+token*request.output_stride+row*4)=sum[token];
                __asm__ volatile("fence rw,rw" ::: "memory");
                result.write_cycles+=tick()-t;result.payload_write+=request.m*4;
            }
            result.rows++;
        }
        result.tiles++;
    }
finish:
    result.cycles=tick()-begin;
    result.other_cycles=result.cycles-result.load_cycles-result.compute_cycles-result.write_cycles;
    result.valid=result.status==0;
    __asm__ volatile("fence rw,rw" ::: "memory");
    return result.status;
}
