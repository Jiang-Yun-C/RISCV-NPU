// Production attention addresses, actual CE/DMA, modeled external AXI memory.
// Reuse the existing model's ready/valid, random stalls and retired W payloads.
#define main ce_general_regression_main
#include "ce_sim.cpp"
#undef main
#include <string>

static constexpr uint64_t SESSION=UINT64_C(0x1122334455667788);
static constexpr uint32_t Y0=0xac00a800,Y1=0xac00af00,Y2=0xac00b600;

struct Outcome {
 int32_t status;unsigned valid,words;uint64_t reads,writes,cycles;
 std::vector<AcceptedTransfer> aw,ar;
};

static void stage_p(Sim &s,uint64_t sequence) {
 check(s.rd(0x124)==0x50574231,"missing local P capability");
 s.wr(0x100,1);s.wr(0x104,448);
 s.wr(0x108,uint32_t(SESSION));s.wr(0x10c,uint32_t(SESSION>>32));
 s.wr(0x110,uint32_t(sequence));s.wr(0x114,uint32_t(sequence>>32));
 s.wr(0x120,1);s.wr(0x128,1);
 for(unsigned h=0;h<7;h++)for(unsigned t=0;t<64;t++)
  s.wr(0x800+(h*64+t)*4,t==0?bits(1.0f):0);
 s.wr(0x118,1);check(s.rd(0x11c)==((448u<<16)|1),"P window did not publish");
}

static Outcome run_pv(Sim &s,uint32_t y,uint32_t v,uint64_t sequence,int expected) {
 s.wr(0x10,1);s.wr(0x30,1000000);s.wr(0x34,0);stage_p(s,sequence);
 std::array<uint32_t,32> desc{};
 desc[0]=0x34364543;desc[1]=1;desc[2]=128;desc[4]=s.rd(0x1c);desc[5]=1;
 desc[8]=0x4c4e3135;desc[9]=96;desc[10]=uint32_t(SESSION);desc[11]=uint32_t(SESSION>>32);
 desc[12]=uint32_t(sequence);desc[13]=uint32_t(sequence>>32);
 desc[14]=5;desc[15]=desc[16]=desc[17]=1;desc[18]=0;desc[19]=y;
 desc[20]=v;desc[24]=7;desc[25]=1;desc[26]=512;desc[27]=1;
 uint32_t epoch=desc[4],generation=++s.generation;
 const uint64_t begin=s.cycles,rb=s.read_bytes,wb=s.write_bytes;
 const size_t aw=s.accepted_aw.size(),ar=s.accepted_ar.size();
 for(unsigned i=0;i<32;i++)s.wr(0x200+4*i,desc[i]);s.wr(0x20,generation);
 uint32_t status=0;
 while(!((status=s.rd(0xc))&16)) {
  for(unsigned i=0;i<47;i++)s.tick();
  check(s.cycles-begin<2000000,"PV completion bounded deadline");
 }
 check(!s.writing&&!s.b_wait&&s.reads.empty()&&s.aw_count==s.b_count,
       "completion before all R/B retirement");
 uint32_t bank=(status&128)?0x500:0x400;std::array<uint32_t,40> c{};
 for(unsigned i=0;i<40;i++)c[i]=s.rd(bank+4*i);
 check(c[3]==epoch,"completion epoch mismatch");
 check(c[10]==uint32_t(SESSION)&&c[11]==uint32_t(SESSION>>32),"completion session mismatch");
 check(c[12]==uint32_t(sequence)&&c[13]==uint32_t(sequence>>32),"completion sequence mismatch");
 check(c[38]==generation&&c[39]==generation,"completion generation mismatch");
 Outcome o{int32_t(c[14]),c[15],0,s.read_bytes-rb,s.write_bytes-wb,s.cycles-begin,
  {s.accepted_aw.begin()+aw,s.accepted_aw.end()},
  {s.accepted_ar.begin()+ar,s.accepted_ar.end()}};
 check(o.status==expected,"unexpected production-address PV status");
 check(o.reads==256,"local P path should read exactly one 256B V row payload");
 if((v&4095u)==4080) {
  check(o.ar.size()==2&&o.ar[0].address==v&&o.ar[0].bytes==16&&
        o.ar[1].address==v+16&&o.ar[1].bytes==240,"short V did not split 16/240 at page boundary");
 } else check(o.ar.size()==1&&o.ar[0].address==v&&o.ar[0].bytes==256,"unexpected V row split");
 const uint64_t completion_reads=uint64_t(c[20])|(uint64_t(c[21])<<32);
 const uint64_t completion_writes=uint64_t(c[22])|(uint64_t(c[23])<<32);
 check(completion_reads==o.reads&&completion_writes==o.writes,"completion payload counters mismatch");
 if(expected==0) {
  check(o.valid==1&&o.writes==1792,"successful PV output size/valid mismatch");
  const std::array<uint32_t,4> lengths=y==Y1?std::array<uint32_t,4>{256,512,512,512}:
    std::array<uint32_t,4>{512,512,512,256};
  check(o.aw.size()==lengths.size(),"unexpected output burst count");
  uint32_t cursor=y;
  for(unsigned i=0;i<lengths.size();i++) {
   check(o.aw[i].address==cursor&&o.aw[i].bytes==lengths[i],"wrong exact output page segmentation");
   cursor+=lengths[i];
  }
  for(unsigned h=0;h<7;h++)for(unsigned i=0;i<64;i++) {
   uint32_t golden=bits(mul(1.0f,fp(s.word(desc[20]+i*4))));
   check(s.word(y+(h*64+i)*4)==golden,"actual accepted output word mismatched FP32 golden");o.words++;
  }
 } else {
  check(o.valid==0&&o.writes==0&&o.aw.empty(),"rejected crossing command emitted output AW/W");
  for(unsigned i=0;i<1792;i++)check(s.byte(y+i)==0xa5,"failed Y output modified");
 }
 s.wr(0x28,generation);
 check(!(s.rd(0xc)&16)&&s.rd(0x11c)==0,"completion ACK did not unlock/revoke local P");
 std::printf("{\"sequence\":%llu,\"y\":\"0x%08x\",\"status\":%d,\"valid\":%u,\"read_bytes\":%llu,\"write_bytes\":%llu,\"words_compared\":%u,\"cycles\":%llu,\"aw\":[",
  (unsigned long long)sequence,y,o.status,o.valid,(unsigned long long)o.reads,
  (unsigned long long)o.writes,o.words,(unsigned long long)o.cycles);
 for(size_t i=0;i<o.aw.size();i++)std::printf("%s{\"address\":\"0x%08x\",\"bytes\":%u}",i?",":"",o.aw[i].address,o.aw[i].bytes);
 std::printf("],\"ar\":[");
 for(size_t i=0;i<o.ar.size();i++)std::printf("%s{\"address\":\"0x%08x\",\"bytes\":%u}",i?",":"",o.ar[i].address,o.ar[i].bytes);
 std::puts("]}");return o;
}

int main(int argc,char **argv) {
 try {
  Verilated::commandArgs(argc,argv);std::fesetround(FE_TONEAREST);
  bool old=argc>1&&std::string(argv[1])=="--expect-old-failure";
  Sim s;s.reset();s.region(0xa8000000,512);s.region(0xa8000ff0,256);s.region(Y0-256,256+(Y2-Y0)+1792+512,0xa5);
  for(unsigned group=0;group<2;group++)for(unsigned i=0;i<64;i++)
   s.word(0xa8000000+group*256+i*4,bits(float(int((group*59+i*17)%151)-75)/83.0f));
  for(unsigned i=0;i<64;i++)s.word(0xa8000ff0+i*4,bits(float(int((i*31)%117)-58)/71.0f));
  uint32_t cap=s.rd(0x130);check(cap==0||cap==0x50563531,"long PV capability malformed");
  auto first=run_pv(s,Y0,0xa8000000,1,0);
  auto second=run_pv(s,Y1,0xa8000100,2,old?-11:0);
  uint32_t status_after_pair=s.rd(0xc);
  // This is a normal next request after ACK in the same live session, not a
  // test of firmware's reset policy or recovery from a physical transport fault.
  // Only the fixed design is required to continue; the old error may latch a
  // fault requiring the normal driver reset procedure before another submit.
  unsigned next_words=0;
  if(!old)next_words=run_pv(s,Y2,0xa8000ff0,3,0).words;
  for(uint32_t a=Y0-256;a<Y0;a++)check(s.byte(a)==0xa5,"write before output region");
  for(uint32_t a=Y2+1792;a<Y2+1792+512;a++)check(s.byte(a)==0xa5,"write after output region");
  check(!s.d.quarantined&&!s.writing&&!s.b_wait&&s.reads.empty(),"final memory/quarantine state");
  std::printf("{\"verdict\":\"%s\",\"long_pv_enabled\":%s,\"production_pair_status\":[%d,%d],\"production_pair_words_compared\":%u,\"ce_status_after_pair\":%u,\"same_session_next_words\":%u}\n",
   old?"EXPECTED_V3_PAGE_FAILURE_REPRODUCED":"V4_PRODUCTION_PAGE_PASS",cap?"true":"false",first.status,second.status,first.words+second.words,status_after_pair,next_words);
  return 0;
 } catch(const std::exception &e) {std::fprintf(stderr,"CE_PRODUCTION_PAGE_FAIL %s\n",e.what());return 1;}
}
