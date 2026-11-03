// Private staging ABI, not the production NX stream descriptor ABI.
#ifndef T27_OBSERVE
#define T27_OBSERVE 0
#endif
#ifdef HOST
static uint64_t pv_marks[6],pv_calls,pv_muls,pv_adds;
#else
#define pv_marks ((volatile uint64_t *)0x20400)
#define pv_calls (*(volatile uint64_t *)0x20440)
#define pv_muls (*(volatile uint64_t *)0x20448)
#define pv_adds (*(volatile uint64_t *)0x20450)
#endif
#define PVMM(n) MM(0x10020000u+(n))
static uint32_t pv_sequence;
int t27_pv_batch(const float *p,const float *v,int stride,int heads,int len,int size,float *out){
 if(heads<1||heads>7||len<1||len>64||size<len||size>64||(size&(size-1)))return 1;
#if T27_OBSERVE
 uint64_t ts=tick();
#endif
#ifdef HOST
 float staged_p[448],staged_v[4096],work[64];
 for(int h=0;h<heads;h++)for(int t=0;t<len;t++)staged_p[h*64+t]=p[h*len+t];
 for(int d=0;d<64;d++)for(int t=0;t<len;t++)staged_v[d*64+t]=v[t*stride+d];
#else
 if(PVMM(0)||pv_sequence==UINT32_MAX)return 2;
 for(int h=0;h<heads;h++)for(int t=0;t<len;t++){union{float f;uint32_t u;}a={.f=p[h*len+t]};PVMM(0x1000+4*(h*64+t))=a.u;}
 for(int d=0;d<64;d++)for(int t=0;t<len;t++){union{float f;uint32_t u;}a={.f=v[t*stride+d]};PVMM(0x1000+4*(448+d*64+t))=a.u;}
#endif
#if T27_OBSERVE
 pv_marks[0]+=tick()-ts;ts=tick();
#endif
#ifndef HOST
 PVMM(4)=len;PVMM(8)=heads;PVMM(12)=size;PVMM(20)=++pv_sequence;
 __asm__ volatile("fence iorw,iorw":::"memory");PVMM(0)=1;
#endif
#if T27_OBSERVE
 pv_marks[1]+=tick()-ts;ts=tick();
#endif
#ifdef HOST
 for(int h=0;h<heads;h++)for(int d=0;d<64;d++){
  for(int t=0;t<size;t++)work[t]=t<len?staged_p[h*64+t]*staged_v[d*64+t]:0.0f;
  for(int n=size;n>1;n/=2)for(int t=0;t<n/2;t++)work[t]=work[2*t]+work[2*t+1];
  out[h*64+d]=work[0];
 }
#else
 unsigned poll=0;while(PVMM(0)!=2){if(++poll>2000000)return 3;}
#endif
#if T27_OBSERVE
 pv_marks[2]+=tick()-ts;ts=tick();
#endif
#ifndef HOST
 __asm__ volatile("fence iorw,iorw":::"memory");
 if(PVMM(16)!=pv_sequence)return 4;
 for(int h=0;h<heads;h++)for(int d=0;d<64;d++){union{float f;uint32_t u;}a={.u=PVMM(0x1000+4*(4608+h*64+d))};out[h*64+d]=a.f;}
#endif
#if T27_OBSERVE
 pv_marks[3]+=tick()-ts;ts=tick();
#endif
#ifndef HOST
 PVMM(24)=pv_sequence;__asm__ volatile("fence iorw,iorw":::"memory");if(PVMM(0))return 5;
#endif
#if T27_OBSERVE
 pv_marks[4]+=tick()-ts;pv_calls++;pv_muls+=(uint64_t)heads*64*len;pv_adds+=(uint64_t)heads*64*(size-1);
#endif
 return 0;
}
