/* One operator submission. Coral owns all groups, restoration and N/M tiles.
 * The only DPI in the simulation is the accepted SRAM storage model. */
#include "linear.h"
#include <stddef.h>
#include <riscv_vector.h>
volatile struct nx_stream_request request __attribute__((section(".request")));
volatile struct nx_stream_result result __attribute__((section(".result")));
static int8_t activation[4*4864] __attribute__((aligned(16)));
static float sa[4*76] __attribute__((aligned(16)));
static float sw[76] __attribute__((aligned(16)));
static int32_t dots[4*76] __attribute__((aligned(16)));
static struct nx_linear_audit audit[4*76] __attribute__((aligned(16)));
static uint64_t tick(void) {
    uint32_t hi,lo,again;
    do { __asm__ volatile("csrr %0, 0xb80":"=r"(hi));
         __asm__ volatile("csrr %0, 0xb00":"=r"(lo));
         __asm__ volatile("csrr %0, 0xb80":"=r"(again)); } while(hi!=again);
    return ((uint64_t)hi<<32)|lo;
}
static uint32_t bits(float f) { union {float f;uint32_t u;} v={.f=f};return v.u; }
static int finite(float f) {return (bits(f)&0x7f800000u)!=0x7f800000u;}
static int scale_ok(float f) {uint32_t u=bits(f);return !(u>>31) && (u==0 || (u>=0x00800000u && u<0x7f800000u));}
static int region(uint32_t a,uint64_t b,int write) {
    uint64_t end=(uint64_t)a+b;
    return b && end<=UINT64_C(0x100000000) &&
       ((!write&&a>=0x80000000u&&end<=0xa8000000u)||
        (a>=0xa8000000u&&end<=0xac000000u)||
        (a>=0xac000000u&&end<=0xb4000000u)||
        (a>=0xba000000u&&end<=0xbc000000u));
}
static int overlaps(uint32_t a,uint64_t an,uint32_t b,uint64_t bn) {
    return (uint64_t)a<(uint64_t)b+bn && (uint64_t)b<(uint64_t)a+an;
}
static int validate(void) {
    if(request.abi!=NX_LINEAR_ABI||request.size!=sizeof(request))return -2;
    if(!(request.session_lo|request.session_hi)||!(request.sequence_lo|request.sequence_hi))return -10;
    if(request.opcode!=NX_STREAM_LINEAR)return -3;
    if(!request.m||!request.n||!request.k)return -1;
    if(request.m>512||request.n>151936||request.k>4864)return -3;
    if(request.row_bytes||request.source_stride||request.destination_stride||request.reserved[1]||request.reserved[2]||request.reserved[3])return -1;
    uint32_t g=(request.k+63)/64,pk=g*64;
    if(request.output_stride<request.n*4)return -4;
    uint64_t out=(uint64_t)(request.m-1)*request.output_stride+request.n*4;
    uint64_t ab=(uint64_t)request.m*request.n*g*16;
    uint32_t a[5]={request.source,request.scales,request.aq,request.sa,request.bias};
    uint64_t b[5]={(uint64_t)request.n*pk,(uint64_t)request.n*g*4,(uint64_t)request.m*pk,(uint64_t)request.m*g*4,(uint64_t)request.n*4};
    if(!region(request.destination,out,1))return -4;
    if(request.reserved[0] && (!region(request.reserved[0],ab,1)||overlaps(request.reserved[0],ab,request.destination,out)))return -4;
    for(unsigned i=0;i<5;i++) {
        if(i==4&&!a[i])continue;
        if(!region(a[i],b[i],0)||overlaps(a[i],b[i],request.destination,out)||
           (request.reserved[0]&&overlaps(a[i],b[i],request.reserved[0],ab)))return -4;
    }
    if((request.destination|request.source|request.scales|request.aq|request.sa|request.bias|request.reserved[0])&15)return -5;
    if(request.output_stride&3)return -5;
    return 0;
}
static void move(uint8_t *dst,const uint8_t *src,uint32_t bytes) {
    while(bytes) {
        uint32_t n=bytes,room=4096-((uintptr_t)src&4095);
        if(n>room)n=room;
        room=4096-((uintptr_t)dst&4095);if(n>room)n=room;
        size_t vl=__riscv_vsetvl_e8m4(n);
        __riscv_vse8_v_u8m4(dst,__riscv_vle8_v_u8m4(src,vl),vl);
        dst+=vl;src+=vl;bytes-=vl;
    }
}
int main(void) {
    uint64_t begin=tick(),load=0,dot_ticks=0,restore=0,write=0,read_bytes=0,write_bytes=0;
    result.abi=NX_LINEAR_ABI;result.size=sizeof(result);
    result.session_lo=request.session_lo;result.session_hi=request.session_hi;
    result.sequence_lo=request.sequence_lo;result.sequence_hi=request.sequence_hi;
    result.valid=0;result.rows=0;result.tiles=0;result.checksum=0;result.reserved=0;
    int status=validate();if(status)goto finish;
    uint32_t m=request.m,n=request.n,k=request.k,g=(k+63)/64,pk=g*64;
    for(uint32_t mb=0;mb<m;mb+=4) {
        uint32_t mt=m-mb<4?m-mb:4;uint64_t t=tick();
        move((uint8_t *)activation,(const uint8_t *)(request.aq+mb*pk),mt*pk);
        move((uint8_t *)sa,(const uint8_t *)(request.sa+mb*g*4),mt*g*4);
        read_bytes+=mt*(pk+g*4);load+=tick()-t;
        for(uint32_t token=0;token<mt;token++)for(uint32_t group=0;group<g;group++) {
            float s=sa[token*g+group];if(!scale_ok(s)){status=-9;goto finish;}
            for(uint32_t j=0;j<64;j++) {
                int q=activation[token*pk+group*64+j];
                if(q==-128 || (!bits(s)&&q) || (group*64+j>=k&&q)){status=-9;goto finish;}
            }
        }
        for(uint32_t base=0;base<n;base+=128) {
            uint32_t end=n-base<128?n:base+128;
            for(uint32_t row=base;row<end;row++) {
                t=tick();move((uint8_t *)sw,(const uint8_t *)(request.scales+row*g*4),g*4);
                float bias=request.bias?*(const volatile float *)(request.bias+row*4):0;
                read_bytes+=g*4+(request.bias?4:0);load+=tick()-t;
                if(!finite(bias)){status=-9;goto finish;}
                t=tick();
                for(uint32_t group=0;group<g;group++) {
                    if(!scale_ok(sw[group])){status=-9;goto finish;}
                    uint32_t count=k-group*64;if(count>64)count=64;
                    size_t vl=__riscv_vsetvl_e8m4(count);
                    vint8m4_t w=__riscv_vle8_v_i8m4((const int8_t *)(request.source+row*pk+group*64),vl);
                    if(__riscv_vcpop_m_b2(__riscv_vmseq_vx_i8m4_b2(w,-128,vl),vl)||
                       (!bits(sw[group])&&__riscv_vcpop_m_b2(__riscv_vmsne_vx_i8m4_b2(w,0,vl),vl))){status=-9;goto finish;}
                    for(uint32_t token=0;token<mt;token++) {
                        vint8m4_t a=__riscv_vle8_v_i8m4(activation+token*pk+group*64,vl);
                        vint16m8_t p=__riscv_vwmul_vv_i16m8(a,w,vl);
                        vint32m1_t z=__riscv_vmv_v_x_i32m1(0,1);
                        dots[group*mt+token]=__riscv_vmv_x_s_i32m1_i32(__riscv_vwredsum_vs_i16m8_i32m1(p,z,vl));
                    }
                }
                read_bytes+=k;dot_ticks+=tick()-t;t=tick();float sums[4]={0,0,0,0};
                for(uint32_t group=0;group<g;group++)for(uint32_t token=0;token<mt;token++) {
                    uint32_t ix=group*mt+token;float p=(float)dots[ix]*sa[token*g+group];
                    float v=p*sw[group];sums[token]=sums[token]+v;
                    if(!finite(p)||!finite(v)||!finite(sums[token])){status=-9;goto finish;}
                    if(request.reserved[0])audit[ix]=(struct nx_linear_audit){dots[ix],p,v,sums[token]};
                }
                for(uint32_t token=0;token<mt;token++) {
                    if(request.bias)sums[token]=sums[token]+bias;
                    if(!finite(sums[token])){status=-9;goto finish;}
                }
                restore+=tick()-t;t=tick();
                for(uint32_t token=0;token<mt;token++)*(volatile float *)(request.destination+(mb+token)*request.output_stride+row*4)=sums[token];
                if(request.reserved[0]) {
                    uint32_t off=(mb*n*g+row*g*mt)*16;
                    move((uint8_t *)(request.reserved[0]+off),(const uint8_t *)audit,mt*g*16);write_bytes+=mt*g*16;
                }
                __asm__ volatile("fence rw,rw" ::: "memory");write_bytes+=mt*4;write+=tick()-t;result.rows++;
            }
            result.tiles++;
        }
    }
finish:
    result.status=status;result.payload_read=read_bytes;result.payload_write=write_bytes;
    result.load_cycles=load;result.compute_cycles=dot_ticks;result.checksum=(uint32_t)restore;result.reserved=(uint32_t)(restore>>32);
    result.write_cycles=write;result.cycles=tick()-begin;
    /* other includes restoration plus validation/control. checksum/reserved
     * hold the low/high halves of the restoration-cycle count. */
    result.other_cycles=result.cycles-load-dot_ticks-write;result.valid=status==0;
    __asm__ volatile("fence rw,rw" ::: "memory");return status;
}
