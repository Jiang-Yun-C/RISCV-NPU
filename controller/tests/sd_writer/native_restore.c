#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define NX_SW_TEST
#define main writer_main
#include "../../firmware/tools/sd_writer/writer.c"
#undef main
static uint8_t *card;
static uint32_t writes,read_fault_lba=~0u;
static int nx_test_read(uint32_t lba,uint8_t *out){if(lba>WRITE_SECTORS)return 5;memcpy(out,card+(size_t)lba*512,512);if(lba==read_fault_lba)out[0]^=1;return 0;}
static int nx_test_write(uint32_t lba,const uint8_t *in){if(lba>=WRITE_SECTORS)return 5;memcpy(card+(size_t)lba*512,in,512);writes++;return 0;}
#define CHECK(x) do{checks++;if(!(x)){fprintf(stderr,"FAIL line %u: %s\n",__LINE__,#x);return 1;}}while(0)
int main(int argc,char **argv){
 if(argc!=3)return 2;unsigned checks=0;card=malloc((size_t)(WRITE_SECTORS+1)*512);if(!card)return 3;
 FILE *f=fopen(argv[1],"rb");if(!f)return 4;CHECK(fread(card,512,OLD_SECTORS,f)==OLD_SECTORS);fclose(f);
 memset(card+(size_t)WRITE_SECTORS*512,0xa7,512);capacity=WRITE_SECTORS+1;next_app=1;tail_restored=0;
 for(unsigned i=0;i<16;i++)cid[i]=i+3;uint8_t out[512],wrong[512]={0};uint32_t n;
 CHECK(dispatch(5,OLD_MODEL_LBA,MODEL_SECTORS,0,0,out,&n)==5&&writes==0);
 CHECK(dispatch(9,RESTORE_TAIL_LBA,1,restore_tail,512,out,&n)==5&&writes==0);
 CHECK(dispatch(4,0,NEW_SECTORS,cid,16,out,&n)==5);
 CHECK(dispatch(3,0,OLD_SECTORS,0,0,out,&n)==0&&eq(out,old_sha,32));
 CHECK(dispatch(4,0,NEW_SECTORS,wrong,16,out,&n)==5&&!armed);
 CHECK(dispatch(4,0,NEW_SECTORS,cid,16,out,&n)==0&&armed&&last_hash_count==0);
 CHECK(dispatch(5,OLD_MODEL_LBA,MODEL_SECTORS,0,0,out,&n)==0&&moved&&writes==MODEL_SECTORS);
 CHECK(dispatch(5,OLD_MODEL_LBA,MODEL_SECTORS,0,0,out,&n)==5);
 f=fopen(argv[2],"rb");if(!f)return 6;CHECK(fread(a,1,512,f)==512&&eq(a,new_header,512));
 for(uint32_t i=1;i<NEW_MODEL_LBA;i++){CHECK(fread(packet,1,512,f)==512);CHECK(dispatch(6,i,1,packet,512,out,&n)==0);}
 CHECK(dispatch(7,0,1,new_header,512,out,&n)==5&&armed);
 memcpy(wrong,restore_tail,512);wrong[7]^=1;CHECK(dispatch(9,RESTORE_TAIL_LBA,1,wrong,512,out,&n)==5);
 CHECK(dispatch(9,RESTORE_TAIL_LBA+1,1,restore_tail,512,out,&n)==5);
 CHECK(dispatch(9,RESTORE_TAIL_LBA,1,restore_tail,512,out,&n)==0&&tail_restored);
 CHECK(dispatch(7,0,1,new_header,512,out,&n)==0&&!armed);
 rewind(f);uint8_t chunk[65536];size_t offset=0,z;
 while((z=fread(chunk,1,sizeof(chunk),f))){CHECK(!memcmp(card+offset,chunk,z));offset+=z;}
 CHECK(offset==(size_t)WRITE_SECTORS*512);fclose(f);
 for(unsigned i=0;i<512;i++)CHECK(card[(size_t)WRITE_SECTORS*512+i]==0xa7);
 CHECK(dispatch(3,0,NEW_SECTORS,0,0,out,&n)==0&&n==32);printf("RESTORED_IMAGE_SHA=");for(unsigned i=0;i<32;i++)printf("%02x",out[i]);puts("");
 armed=moved=1;next_app=1;read_fault_lba=1;CHECK(dispatch(6,1,1,packet,512,out,&n)==7&&next_app==1);
 CHECK(write_block(WRITE_SECTORS,packet)==5);
 printf("SD_RESTORE_NATIVE_PASS checks=%u writes=%u\n",checks,writes);free(card);return 0;
}
