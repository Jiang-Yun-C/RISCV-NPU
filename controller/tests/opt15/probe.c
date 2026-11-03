/* Host source-equation probe. Includes the pinned upstream scale macro.
 * This is neither Gemmini RTL simulation nor RV32 firmware timing. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <math.h>
#include "gemmini_params.h"

static uint32_t bits(float x) { uint32_t u; memcpy(&u,&x,4); return u; }
static void get(void *p, size_t size, FILE *f) {
  if (fread(p,1,size,f)!=size) { fputs("fixture truncated\n",stderr); exit(2); }
}
int main(int argc, char **argv) {
  if (argc!=2) return 2;
  FILE *f=fopen(argv[1],"rb"); if (!f) return 2;
  uint32_t count; get(&count,4,f);
  printf("SCALE %d %.9g\n",(int)ACC_SCALE(1,0.25f),0.25);
  /* Real upstream operand layout: rows[63:48], cols[47:32], addr[31:0]. */
  uint64_t rs2=((uint64_t)4<<48)|((uint64_t)16<<32)|0x1234;
  printf("OPERAND %016llx %08x\n",(unsigned long long)rs2,(uint32_t)rs2);
  for (uint32_t t=0;t<count;t++) {
    uint32_t m,n,k; get(&m,4,f);get(&n,4,f);get(&k,4,f);
    uint32_t g=(k+63)/64;
    int8_t *a=malloc(m*k),*w=malloc(n*k);
    float *sa=malloc(m*g*4),*sw=malloc(n*g*4),*bias=malloc(n*4);
    if (!a||!w||!sa||!sw||!bias) return 2;
    get(a,m*k,f);get(w,n*k,f);get(sa,m*g*4,f);get(sw,n*g*4,f);get(bias,n*4,f);
    for(uint32_t i=0;i<m;i++)for(uint32_t j=0;j<n;j++) {
      float y=0;
      for(uint32_t h=0;h<g;h++) {
        int32_t dot=0;
        for(uint32_t x=h*64;x<k && x<(h+1)*64;x++)dot+=(int32_t)a[i*k+x]*w[j*k+x];
        float p=(float)dot*sa[i*g+h];
        float v=p*sw[j*g+h];
        y=y+v;
        printf("D %u %u %u %u %d\n",t,i,j,h,dot);
      }
      y=y+bias[j];printf("Y %u %u %u %08x\n",t,i,j,bits(y));
    }
    free(a);free(w);free(sa);free(sw);free(bias);
  }
  if (fgetc(f)!=EOF) return 2;
  fclose(f);return 0;
}
