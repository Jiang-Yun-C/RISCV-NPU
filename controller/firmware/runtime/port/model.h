#ifndef NXR_MODEL_H
#define NXR_MODEL_H
#include "runtime.h"
#include "nx_reference.h"
typedef struct { nx_session *session; float *logits; } nxr_model;
int nxr_attach(nxr_request *,nxr_model *,nx_session *,float *,uint32_t vocab);
size_t nxr_request_bytes(void);
size_t nxr_model_bytes(void);
int nxr_state(const nxr_request *);
uint32_t nxr_count(const nxr_request *);
uint32_t nxr_reason(const nxr_request *);
uint32_t nxr_output(const nxr_request *,uint32_t);
#endif
