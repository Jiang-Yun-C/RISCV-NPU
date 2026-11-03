/* Include the exact candidate reference so its static attention kernel is used. */
#include "nx_reference.c"
int nx_opt12_attention_probe(int past){
    nx_session probe={0};
    probe.q=(float *)(uintptr_t)0xaf000000;
    probe.a=(float *)(uintptr_t)0xaf002000;
    probe.k=(float (*)[S][KV])(uintptr_t)0xaf010000;
    probe.v=(float (*)[S][KV])(uintptr_t)0xaf040000;
    return attention(&probe,0,1,past);
}
