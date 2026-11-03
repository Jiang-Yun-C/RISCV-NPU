#ifndef NXR_CORAL_API_COMPAT_H
#define NXR_CORAL_API_COMPAT_H
/* T08's source-level descriptors and T11's C kernels predate integration and
 * share several identifiers. Qualify only those driver header identifiers;
 * object layouts, exported functions and numeric/reference ABI stay intact. */
#define NX_OK NX_ACCEL_OK
#define NX_LINEAR NX_ACCEL_LINEAR
#define NX_ROPE NX_ACCEL_ROPE
#define NX_SWIGLU NX_ACCEL_SWIGLU
#define nx_linear nx_accel_linear
#include "coral_linear.h"
#undef nx_linear
#undef NX_SWIGLU
#undef NX_ROPE
#undef NX_LINEAR
#undef NX_OK
#endif
