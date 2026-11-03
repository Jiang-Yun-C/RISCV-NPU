#include "loader.h"
#include "sha256.h"
#include "trusted.h"
#include "runtime.h"
#define SPI(o) (*(volatile uint32_t *)(uintptr_t)(0x10002000u+(o)))
#define UART(o) (*(volatile uint32_t *)(uintptr_t)(0x10000000u+(o)))
#ifndef NX_SD_INIT_RETRIES
#define NX_SD_INIT_RETRIES 32u
#endif
#ifndef NX_SD_TOKEN_POLLS
#define NX_SD_TOKEN_POLLS 128u
#endif
#define SCRATCH __attribute__((section(".sd_scratch")))
static uint8_t sector[512] SCRATCH,header[192] SCRATCH,media[128] SCRATCH;
static uint32_t lba,cached,position,file_size,error,entries;
static nx_sha whole SCRATCH,h SCRATCH,payload SCRATCH;
static uint8_t chunk[64] SCRATCH;
static uint32_t ticks(void){uint32_t t;__asm__ volatile("csrr %0,mcycle":"=r"(t));return t;}
static uint32_t u32(const uint8_t *p){return (uint32_t)p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;}
static uint64_t u64(const uint8_t *p){return (uint64_t)u32(p)|((uint64_t)u32(p+4)<<32);}
static int same(const uint8_t *a,const uint8_t *b,unsigned n){while(n--)if(*a++!=*b++)return 0;return 1;}
static int zeros(const uint8_t *p,unsigned n){while(n--)if(*p++)return 0;return 1;}
static int name(const uint8_t *p,const char *q){unsigned i=0;while(q[i]&&i<127){if(p[i]!=(uint8_t)q[i])return 0;i++;}return p[i]==0&&q[i]==0;}
static uint8_t transfer(uint8_t v){SPI(8)=v;while(SPI(0)&1u){}return (uint8_t)SPI(12);}
static void select(int on){SPI(16)=on?0:1;transfer(255);}
static uint8_t crc7(const uint8_t *p,unsigned n){uint8_t c=0;while(n--){uint8_t v=*p++;for(unsigned i=0;i<8;i++){c<<=1;if((v^c)&128)c^=9;v<<=1;}}return (uint8_t)(c<<1)|1;}
#include "crc16_table.h"
static uint16_t crc16(uint16_t c,uint8_t v){return (uint16_t)((c<<8)^nx_crc16_table[(c>>8)^v]);}
static uint32_t crc32(const uint8_t *p,unsigned n){uint32_t c=~0u;while(n--){c^=*p++;for(unsigned i=0;i<8;i++)c=(c>>1)^((0u-(c&1u))&0xedb88320u);}return ~c;}
static uint8_t command(unsigned cmd,uint32_t arg){
    uint8_t p[6]={0x40u|cmd,arg>>24,arg>>16,arg>>8,arg,0};p[5]=crc7(p,5);
    for(unsigned i=0;i<6;i++)transfer(p[i]);
    for(unsigned i=0;i<16;i++){uint8_t v=transfer(255);if(!(v&128))return v;}
    error=E_TIMEOUT;return 255;
}
static int initialize(void){
    SPI(4)=249;SPI(16)=1;for(unsigned i=0;i<10;i++)transfer(255);select(1);
    if(command(0,0)!=1)return error?error:E_CARD;
    select(0);select(1);if(command(8,0x1aa)!=1)return error?error:E_CARD;
    uint32_t echo=0;for(unsigned i=0;i<4;i++)echo=(echo<<8)|transfer(255);
    if(echo!=0x1aa)return E_CARD;
    int ready=0;
    for(unsigned i=0;i<NX_SD_INIT_RETRIES;i++){
        select(0);select(1);if(command(55,0)>1)return error?error:E_CARD;
        select(0);select(1);uint8_t r=command(41,0x40000000u);if(r==0){ready=1;break;}if(r!=1)return error?error:E_CARD;
    }
    if(!ready)return E_TIMEOUT;
    select(0);select(1);if(command(58,0)!=0)return error?error:E_CARD;
    uint32_t ocr=0;for(unsigned i=0;i<4;i++)ocr=(ocr<<8)|transfer(255);
    if((ocr&0xc0ff8000u)!=0xc0ff8000u)return E_CARD; /* SDHC, powered, 2.7--3.6 V */
    select(0);SPI(4)=3;return SD_OK;
}
static int block(uint32_t address){
    select(1);if(command(17,address)!=0){select(0);return error?error:E_CARD;}
    uint8_t token=255;for(unsigned i=0;i<NX_SD_TOKEN_POLLS&&token==255;i++)token=transfer(255);
    if(token!=254){select(0);return token==255?E_TIMEOUT:E_CARD;}
    SPI(0x38)=514;
    uint16_t crc=0;for(unsigned i=0;i<512;i++){sector[i]=(uint8_t)SPI(0x3c);crc=crc16(crc,sector[i]);}
    uint16_t actual=(uint16_t)SPI(0x3c)<<8;actual|=(uint8_t)SPI(0x3c);select(0);
    return actual==crc?SD_OK:E_CRC;
}
static void open_file(uint32_t start,uint32_t bytes){lba=start;file_size=bytes;position=0;cached=~0u;nx_sha_init(&whole);}
static int read_bytes(uint8_t *out,unsigned n){
    if(n>file_size-position)return E_BOUNDS;
    while(n){uint32_t index=position/512;
        if(index!=cached){int rc=block(lba+index);if(rc)return rc;cached=index;}
        unsigned take=512-position%512;if(take>n)take=n;
        nx_sha_add(&whole,sector+position%512,take);
        for(unsigned i=0;i<take;i++)out[i]=sector[position%512+i];
        out+=take;position+=take;n-=take;
    }return 0;
}
static int pin(const uint8_t *hash,const uint8_t hashes[][32],unsigned count){for(unsigned i=0;i<count;i++)if(same(hash,hashes[i],32))return 1;return 0;}
static uint8_t *entry(unsigned i){return (uint8_t *)(uintptr_t)(NX_DIRECTORY+i*256);}
static uint32_t address(const uint8_t *e){return (u32(e+176)==1?0x80000000u:0xb8000000u)+u32(e+184);}
static uint64_t align64(uint64_t n){return (n+63)&~(uint64_t)63;}
static int check_entry(unsigned i,uint32_t data){
    const uint8_t *e=entry(i);unsigned stop=0;while(stop<128&&e[stop])stop++;
    if(!stop||stop==128||!zeros(e+stop,128-stop)||e[0]=='/')return E_METADATA;
    for(unsigned j=0;j<stop;j++)if(!((e[j]>='a'&&e[j]<='z')||(e[j]>='A'&&e[j]<='Z')||(e[j]>='0'&&e[j]<='9')||e[j]=='_'||e[j]=='/'||e[j]=='-'||e[j]=='.')||(j&&e[j]=='.'&&e[j-1]=='.'))return E_METADATA;
    for(unsigned j=0;j<i;j++)if(same(e,entry(j),128))return E_DUPLICATE;
    uint32_t kind=u32(e+128),rank=u32(e+136),flags=u32(e+140),region=u32(e+176),alias=u32(e+180);
    uint64_t offset=u64(e+160),length=u64(e+168),relative=u64(e+184),end;
    if(!zeros(e+224,32))return E_RESERVED;
    if(kind<1||kind>4||u32(e+132)!=0x1000+kind)return E_LAYOUT;
    if(flags>1||(flags==1)!=(alias!=~0u))return E_ALIAS;
    if(region<1||region>2)return E_BOUNDS;
    if(rank!=(kind<3?2u:kind==3?1u:0u)||!zeros(e+144+rank*4,(4-rank)*4))return E_SHAPE;
    uint64_t product=1;
    for(unsigned j=0;j<rank;j++){uint32_t d=u32(e+144+j*4);if(!d)return E_SHAPE;if(product>UINT64_MAX/d)return E_OVERFLOW;product*=d;}
    if(rank){uint64_t expected;if(kind==1){uint64_t k=align64(u32(e+148));if(k>UINT64_MAX/u32(e+144))return E_OVERFLOW;expected=k*u32(e+144);}else{if(product>UINT64_MAX/4)return E_OVERFLOW;expected=product*4;}if(expected!=length)return E_SHAPE;}
    if(!length||length>UINT64_MAX-offset||length>UINT64_MAX-relative)return E_OVERFLOW;
    uint64_t base=region==1?0x80000000u:0xb8000000u;
    if(relative>UINT32_MAX-base||length>UINT32_MAX-base-relative)return E_OVERFLOW;
    if(nxr_file_span(offset,length,1,file_size,&end)||offset<data||relative+length>(region==1?0x28000000u:0x02000000u))return E_BOUNDS;
    if((offset|relative)&63)return E_ALIGNMENT;
    int tokenizer=kind==4&&same(e,(const uint8_t *)"tokenizer/",10);
    if(tokenizer!=(region==2))return E_METADATA;
    if(flags){
        if(alias>=i)return E_ALIAS;
        const uint8_t *t=entry(alias);const char *src=kind==1?"model.embed_tokens.weight":"model.embed_tokens.weight.scale";
        const char *dst=kind==1?"lm_head.weight":"lm_head.weight.scale";
        if(kind>2||!name(e,dst)||!name(t,src)||u32(t+140)||!same(e+128,t+128,12)||!same(e+144,t+144,36)||!same(e+184,t+184,40))return E_ALIAS;
    }
    return 0;
}
static int numeric(void){
    unsigned aliases=0;int metadata=0;
    for(unsigned i=0;i<entries;i++){
        const uint8_t *e=entry(i);uint32_t kind=u32(e+128);if(u32(e+140)){aliases++;continue;}
        if(name(e,"metadata.json")){if(kind!=4||u64(e+168)>(1u<<20))return E_METADATA;metadata=1;}
        if(kind==1){
            const uint8_t *s=0;unsigned len=0;while(e[len])len++;
            for(unsigned j=0;j<entries;j++){const uint8_t *t=entry(j);if(same(t,e,len)&&name(t+len,".scale")){s=t;break;}}
            uint32_t n=u32(e+144),k=u32(e+148),groups=(k+63)/64;
            if(!s||u32(s+128)!=2||u32(s+140)||u32(s+144)!=n||u32(s+148)!=groups)return E_SHAPE;
            const volatile uint8_t *q=(const volatile uint8_t *)(uintptr_t)address(e);
            const volatile uint32_t *scales=(const volatile uint32_t *)(uintptr_t)address(s);
            for(uint32_t row=0;row<n;row++)for(uint32_t g=0;g<groups;g++){
                uint32_t sw=scales[row*groups+g];if((sw&0x80000000u)||(sw&0x7f800000u)==0x7f800000u||(sw&&!(sw&0x7f800000u)))return E_NUMERIC;
                for(unsigned c=0;c<64;c++){uint8_t v=q[(row*groups+g)*64+c];if(v==128||(!sw&&v)||(g*64+c>=k&&v))return E_NUMERIC;}
            }
        }else if(kind==2){
            unsigned len=0;while(e[len])len++;if(len<6||!name(e+len-6,".scale"))return E_SHAPE;
            int found=0;for(unsigned j=0;j<entries;j++)if(u32(entry(j)+128)==1&&same(entry(j),e,len-6)&&entry(j)[len-6]==0)found=1;
            if(!found)return E_SHAPE;
        }else if(kind==3){const volatile uint32_t *p=(const volatile uint32_t *)(uintptr_t)address(e);for(unsigned j=0;j<u32(e+168)/4;j++)if((p[j]&0x7f800000u)==0x7f800000u)return E_NUMERIC;}
    }
    if(aliases!=2||!metadata)return aliases!=2?E_ALIAS:E_METADATA;
    return 0;
}
static int model(uint32_t start,uint32_t bytes,const uint8_t expected[32]){
    open_file(start,bytes);int rc=read_bytes(header,192);if(rc)return rc;
    if(!same(header,(const uint8_t *)"NXW8PK1\0",8))return E_MAGIC;
    if(u32(header+8)!=1||u32(header+12)!=160||u32(header+36)!=256)return E_VERSION;
    if(u32(header+16)!=0x01020304)return E_ENDIAN;
    if(u32(header+20)!=0x1001||u32(header+24)!=64)return E_LAYOUT;
    if(u32(header+28)!=64)return E_ALIGNMENT;
    uint8_t hash[32];nx_sha_init(&h);nx_sha_add(&h,header,128);nx_sha_end(&h,hash);if(!same(hash,header+128,32))return E_CHECKSUM;
    entries=u32(header+32);uint64_t data=u64(header+48);
    if(!entries||entries>NX_DIRECTORY_LIMIT||u64(header+56)!=bytes||u64(header+40)!=192||data!=192+entries*256||data>=bytes||(bytes&63))return E_BOUNDS;
    if(!zeros(header+160,32))return E_RESERVED;
    nx_sha_init(&h);
    for(unsigned i=0;i<entries;i++){rc=read_bytes(entry(i),256);if(rc)return rc;nx_sha_add(&h,entry(i),256);}
    nx_sha_end(&h,hash);if(!same(hash,header+64,32))return E_CHECKSUM;
    for(unsigned i=0;i<entries;i++){rc=check_entry(i,(uint32_t)data);if(rc)return rc;}
    for(unsigned i=0;i<entries;i++)if(!u32(entry(i)+140))for(unsigned j=0;j<i;j++)if(!u32(entry(j)+140)){
        const uint8_t *a=entry(i),*b=entry(j);uint64_t x=u64(a+160),y=u64(b+160),xl=u64(a+168),yl=u64(b+168);
        if(x<y+yl&&y<x+xl)return E_OVERLAP;
        x=u64(a+184);y=u64(b+184);if(u32(a+176)==u32(b+176)&&x<y+yl&&y<x+xl)return E_OVERLAP;
    }
    uint64_t cursor=data,regions[2]={0,0};
    for(unsigned i=0;i<entries;i++)if(!u32(entry(i)+140)){
        uint8_t *e=entry(i);unsigned r=u32(e+176)-1;
        if(u64(e+160)!=cursor||u64(e+184)!=regions[r])return E_BOUNDS;
        cursor=align64(cursor+u64(e+168));regions[r]=align64(regions[r]+u64(e+168));
    }
    if(cursor!=bytes)return E_BOUNDS;
    nx_sha_init(&payload);
    for(unsigned i=0;i<entries;i++)if(!u32(entry(i)+140)){
        uint8_t *e=entry(i);uint32_t left=u32(e+168),dest=address(e);nx_sha_init(&h);
        while(left){unsigned n=left>64?64:left;rc=read_bytes(chunk,n);if(rc)return rc;nx_sha_add(&h,chunk,n);nx_sha_add(&payload,chunk,n);
            for(unsigned j=0;j<n;j++){*(volatile uint8_t *)(uintptr_t)(dest+j)=chunk[j];}
            dest+=n;left-=n;}
        nx_sha_end(&h,hash);if(!same(hash,e+192,32))return E_CHECKSUM;
        unsigned pad=(unsigned)(align64(position)-position);if(pad){rc=read_bytes(chunk,pad);if(rc)return rc;if(!zeros(chunk,pad))return E_RESERVED;nx_sha_add(&payload,chunk,pad);}
    }
    nx_sha_end(&payload,hash);if(!same(hash,header+96,32))return E_CHECKSUM;
    nx_sha_end(&whole,hash);if(!same(hash,expected,32))return E_CHECKSUM;
    __asm__ volatile("fence iorw,iorw\n.word 0x0000500f" ::: "memory");
    rc=numeric();if(rc)return rc;
    if(!pin(hash,nx_trusted_models,NX_TRUSTED_MODELS))return E_CHECKSUM;
    int32_t dot=0;const volatile int8_t *q=(const volatile int8_t *)(uintptr_t)address(entry(0));
    for(unsigned i=0;i<64;i++){dot+=q[i];}
    unsigned trusted=0;while(trusted<NX_TRUSTED_MODELS&&!same(hash,nx_trusted_models[trusted],32))trusted++;
    if(trusted==NX_TRUSTED_MODELS||dot!=nx_trusted_dot[trusted])return E_SELFTEST;
    SPI(0x28)=(uint32_t)dot;SPI(0x2c)=entries;
    return 0;
}
uint32_t nx_sd_boot(void){
    error=0;SPI(0x18)=0;SPI(0x1c)=0;entries=0;
    uint32_t begin=ticks();while(!SPI(0x34))if(ticks()-begin>1000000)return E_TIMEOUT;
    int rc=initialize();if(rc)return rc;
    rc=block(0);if(rc)return rc;for(unsigned i=0;i<128;i++)media[i]=sector[i];
    if(!same(sector,(const uint8_t *)"NXSDV1\0\0",8)||u32(sector+8)!=1||u32(sector+12)!=512||crc32(sector,508)!=u32(sector+508)||!zeros(sector+108,400))return E_MEDIA;
    uint32_t count=u32(media+16),app_lba=u32(media+20),app_bytes=u32(media+24),base=u32(media+28),entry_pc=u32(media+32),model_lba=u32(media+68),model_bytes=u32(media+72);
    if(!app_bytes||!model_bytes||base<0xb4000000u||base>=0xb7ff0000u||app_bytes>0xb7ff0000u-base||entry_pc<base||entry_pc-base>=app_bytes||(entry_pc&3))return E_BOUNDS;
    uint64_t app_end=(uint64_t)app_lba+((uint64_t)app_bytes+511)/512,model_end=(uint64_t)model_lba+((uint64_t)model_bytes+511)/512;
    if(app_end>UINT32_MAX||model_end>UINT32_MAX)return E_OVERFLOW;
    if(app_lba!=1||model_lba!=app_end||model_end!=count)return E_BOUNDS;
    open_file(app_lba,app_bytes);uint8_t hash[32];uint32_t dest=base;
    while(position<app_bytes){unsigned n=app_bytes-position>64?64:app_bytes-position;rc=read_bytes(chunk,n);if(rc)return rc;for(unsigned i=0;i<n;i++)*(volatile uint8_t *)(uintptr_t)(dest+i)=chunk[i];dest+=n;}
    nx_sha_end(&whole,hash);if(!same(hash,media+36,32)||!pin(hash,nx_trusted_apps,NX_TRUSTED_APPS))return E_CHECKSUM;
    rc=model(model_lba,model_bytes,media+76);if(rc)return rc;
    __asm__ volatile("fence iorw,iorw\n.word 0x0000500f\nfence.i" ::: "memory");
    SPI(0x18)=1;((void (*)(void))(uintptr_t)entry_pc)();return 0;
}
int main(void){uint32_t generation=0;UART(0x30)=2;
    for(;;){while(SPI(0x24)==generation){}generation=SPI(0x24);uint32_t rc=nx_sd_boot();select(0);SPI(0x1c)=rc;SPI(0x20)=generation;}
}
