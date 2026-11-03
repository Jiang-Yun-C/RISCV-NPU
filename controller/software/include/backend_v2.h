#ifndef NEXUSRV_BACKEND_V2_H
#define NEXUSRV_BACKEND_V2_H
#include "backend_v1.h"
#define NX_API_VERSION_V2 2u
#define NX_CE64 2u
typedef struct {
    nx_caps base;
    uint32_t implemented_profiles, qualified_profile_mask;
} nx_caps_v2;
/* API1 retains CPU_C=0/CORAL_RVV=1 and rejects route2. API2 clients explicitly
 * select CE64 and inspect the independent board qualification mask. */
#endif
