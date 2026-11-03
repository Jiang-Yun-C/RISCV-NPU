#ifndef NX_TEXT_DIAG_H
#define NX_TEXT_DIAG_H
#ifndef __ASSEMBLER__
#include <stdint.h>
void nx_diag_init(void);
void nx_diag_phase(uint32_t,uint32_t,int32_t,uint32_t);
void nx_diag_context(uint32_t,const void *);
void nx_diag_capture(uint32_t,int,const void *,const void *,const void *);
int nx_diag_state(uint32_t,void *);
int nx_diag_runtime(uint32_t,int,const void *);
void nx_diag_dump(void (*)(char));
void nx_diag_recovery(int);
void nx_diag_budget(uint64_t,uint64_t,uint64_t,uint64_t);
void nx_diag_backend_enter(void *);
void nx_diag_reference(uint32_t,int,int,int,uint64_t,uint64_t);
void nx_diag_vector(const void *,const void *);
#endif
#endif
