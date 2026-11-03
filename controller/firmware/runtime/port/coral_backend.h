#ifndef NXR_CORAL_BACKEND_H
#define NXR_CORAL_BACKEND_H
#include "nx_reference.h"
/* Opaque accelerator context is owned by the platform. The shared buffers
 * must be noncached, disjoint, and large enough for one complete operator. */
typedef struct {
    void *accelerator;
    float *input, *output;
    uint32_t input_bytes, output_bytes;
    uint64_t timeout_ticks;
} nxr_coral_backend;
int nxr_coral_linear(void *,const float *,int,const nx_matrix *,float *);
#endif
