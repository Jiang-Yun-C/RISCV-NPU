#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define NX_SW_TEST
#define main writer_main
#include "../../firmware/tools/sd_writer/writer.c"
#undef main
static uint8_t *card;
static uint32_t writes,read_fault_lba=~0u;
static int nx_test_read(uint32_t lba,uint8_t *out){if(lba>=NEW_SECTORS+1)return 5;memcpy(out,card+(size_t)lba*512,512);if(lba==read_fault_lba)out[0]^=1;return 0;}
static int nx_test_write(uint32_t lba,const uint8_t *in){if(lba>=NEW_SECTORS)return 5;memcpy(card+(size_t)lba*512,in,512);writes++;return 0;}
#define CHECK(x) do{checks++;if(!(x)){fprintf(stderr,"FAIL line %u: %s\n",__LINE__,#x);return 1;}}while(0)
int main(int argc,char **argv){if(argc!=3)return 2;unsigned checks=0;card=malloc((size_t)(NEW_SECTORS+1)*512);if(!card)return 3;FILE *f=fopen(argv[1],"rb");if(!f)return 4;CHECK(fread(card,512,OLD_SECTORS,f)==OLD_SECTORS);fclose(f);memset(card+(size_t)OLD_SECTORS*512,0xa7,1024);capacity=NEW_SECTORS+1;next_app=1;for(unsigned i=0;i<16;i++)cid[i]=i+3;uint8_t out[512],wrong[16]={0};uint32_t n=0;uint8_t untouched[512];memcpy(untouched,card+(size_t)NEW_SECTORS*512,512);
 CHECK(crc32((const uint8_t*)"123456789",9)==0xcbf43926u);CHECK(crc7((const uint8_t*)"\x40\0\0\0\0",5)==0x95);uint16_t crc=0;for(unsigned i=0;i<9;i++)crc=crc16(crc,(uint8_t)"123456789"[i]);CHECK(crc==0x31c3);
 CHECK(dispatch(6,1,1,card+512,512,out,&n)==5&&writes==0);CHECK(dispatch(5,OLD_MODEL_LBA,MODEL_SECTORS,0,0,out,&n)==5&&writes==0);CHECK(dispatch(4,0,NEW_SECTORS,cid,16,out,&n)==5&&!armed);CHECK(dispatch(3,1,OLD_SECTORS,0,0,out,&n)==5);
 CHECK(dispatch(3,0,OLD_SECTORS,0,0,out,&n)==0&&n==32&&eq(out,old_sha,32));CHECK(dispatch(4,0,NEW_SECTORS,wrong,16,out,&n)==5&&!armed);CHECK(dispatch(4,0,NEW_SECTORS,cid,16,out,&n)==0&&armed);CHECK(dispatch(6,1,1,card+512,512,out,&n)==5&&writes==0);
 CHECK(dispatch(5,OLD_MODEL_LBA,MODEL_SECTORS,0,0,out,&n)==0&&moved&&writes==MODEL_SECTORS);CHECK(dispatch(5,OLD_MODEL_LBA,MODEL_SECTORS,0,0,out,&n)==5);
 CHECK(dispatch(6,0,1,new_header,512,out,&n)==5);CHECK(dispatch(7,0,1,new_header,512,out,&n)==5);
 f=fopen(argv[2],"rb");if(!f)return 5;CHECK(fread(a,1,512,f)==512&&eq(a,new_header,512));for(uint32_t i=1;i<NEW_MODEL_LBA;i++){CHECK(fread(packet,1,512,f)==512);CHECK(dispatch(6,i,1,packet,512,out,&n)==0);}CHECK(dispatch(7,0,1,new_header,512,out,&n)==0&&!armed);
 CHECK(dispatch(3,0,NEW_SECTORS,0,0,out,&n)==0&&n==32);printf("NEW_SHA=");for(unsigned i=0;i<32;i++)printf("%02x",out[i]);printf("\n");
 rewind(f);uint8_t chunk[65536];size_t offset=0,z;while((z=fread(chunk,1,sizeof(chunk),f))){CHECK(memcmp(card+offset,chunk,z)==0);offset+=z;}CHECK(offset==(size_t)NEW_SECTORS*512);fclose(f);CHECK(eq(untouched,card+(size_t)NEW_SECTORS*512,512));
 armed=moved=1;next_app=1;memset(packet,0x3b,512);read_fault_lba=1;CHECK(dispatch(6,1,1,packet,512,out,&n)==7);CHECK(next_app==1);CHECK(write_block(NEW_SECTORS,packet)==5);printf("SD_WRITER_NATIVE_PASS checks=%u writes=%u\n",checks,writes);free(card);return 0;}
