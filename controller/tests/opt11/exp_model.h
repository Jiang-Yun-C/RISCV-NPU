/* Host execution model of the Q96 RTL datapath, for cumulative T05 validation.
 * This is a DUT model; independent truth remains the original T11/T05 oracle.
 * No table is populated from DUT output or real model activations. */
#ifndef NX_OPT11_EXP_MODEL_H
#define NX_OPT11_EXP_MODEL_H
#include <stdint.h>
typedef unsigned __int128 nx_u128;
static nx_u128 nx_opt11_product_q96(nx_u128 a,nx_u128 b){
    nx_u128 p0=(nx_u128)(uint64_t)a*(uint64_t)b;
    nx_u128 p1=(a>>64)*(uint64_t)b+(b>>64)*(uint64_t)a+(p0>>64);
    nx_u128 p2=(a>>64)*(b>>64)+(p1>>64);
    return (p2<<32)|((uint64_t)p1>>32);
}
static float nx_opt11_exp_model(float input){
    union {float f;uint32_t u;} v={.f=input};uint32_t a=v.u&0x7fffffffu;
    static const nx_u128 coefficients[22]={(((nx_u128)0x100000000ULL<<64)|0x0000000000000000ULL),
(((nx_u128)0x100000000ULL<<64)|0x0000000000000000ULL),
(((nx_u128)0x80000000ULL<<64)|0x0000000000000000ULL),
(((nx_u128)0x2aaaaaaaULL<<64)|0xaaaaaaaaaaaaaaabULL),
(((nx_u128)0xaaaaaaaULL<<64)|0xaaaaaaaaaaaaaaabULL),
(((nx_u128)0x2222222ULL<<64)|0x2222222222222222ULL),
(((nx_u128)0x5b05b0ULL<<64)|0x5b05b05b05b05b06ULL),
(((nx_u128)0xd00d0ULL<<64)|0x0d00d00d00d00d01ULL),
(((nx_u128)0x1a01aULL<<64)|0x01a01a01a01a01a0ULL),
(((nx_u128)0x2e3bULL<<64)|0xc74aad8e671f5584ULL),
(((nx_u128)0x49fULL<<64)|0x93edde27d71cbbc0ULL),
(((nx_u128)0x6bULL<<64)|0x99159fd5138e3f9dULL),
(((nx_u128)0x8ULL<<64)|0xf76c77fc6c4bdaa2ULL),
(((nx_u128)0x0ULL<<64)|0xb092309d43684be5ULL),
(((nx_u128)0x0ULL<<64)|0x0c9cba54603e4e90ULL),
(((nx_u128)0x0ULL<<64)|0x00d73f9f399dc0f9ULL),
(((nx_u128)0x0ULL<<64)|0x000d73f9f399dc10ULL),
(((nx_u128)0x0ULL<<64)|0x0000ca963b81856aULL),
(((nx_u128)0x0ULL<<64)|0x00000b413c31dcbfULL),
(((nx_u128)0x0ULL<<64)|0x00000097a4da340aULL),
(((nx_u128)0x0ULL<<64)|0x00000007950ae901ULL),
(((nx_u128)0x0ULL<<64)|0x000000005c6e3bdbULL)};
    const nx_u128 ln2=(((nx_u128)0xb17217f7ULL<<64)|0xd1cf79abc9e3b398ULL);
    if(a>=0x42d00000u){v.u=0;return v.f;}
    unsigned encoded=a>>23;
    if(encoded<31){v.u=0x3f800000u;return v.f;}
    nx_u128 remainder=(a&0x7fffffu)|0x800000u;
    if(encoded>=54)remainder<<=encoded-54;else remainder>>=54-encoded;
    unsigned power=0;
    while(remainder>=ln2){remainder-=ln2;power++;}
    nx_u128 y=coefficients[21];
    for(int k=20;k>=0;k--)y=coefficients[k]-nx_opt11_product_q96(remainder,y);
    int lead=0;
    for(int k=0;k<97;k++)if((y>>k)&1)lead=k;
    int exponent=lead-96-(int)power;
    int sh=exponent < -126 ? (int)power-53 : lead-23;
    nx_u128 mant=sh>=0?y>>sh:y<<(-sh);
    unsigned guard=sh>0?(unsigned)((y>>(sh-1))&1):0;
    unsigned sticky=sh>1&&(y&(((nx_u128)1<<(sh-1))-1))!=0;
    uint32_t rounded=(uint32_t)mant+(guard&&(sticky||(mant&1)));
    if(exponent < -126)v.u=rounded;
    else if(rounded&0x1000000u)v.u=(uint32_t)(exponent+128)<<23;
    else v.u=((uint32_t)(exponent+127)<<23)|(rounded&0x7fffffu);
    return v.f;
}
#endif
