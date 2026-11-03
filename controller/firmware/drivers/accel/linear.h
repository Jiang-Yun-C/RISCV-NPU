#ifndef NX_CORAL_LINEAR_H
#define NX_CORAL_LINEAR_H
#include "stream.h"
/* T15 uses the 96-byte request/104-byte result containers, with a new ABI.
 * source=Wq (physical padded rows), scales=Sw, aq/sa=packed activation.
 * reserved[0]=optional qualification audit address; all other reserved fields
 * and COPY fields must be zero for public requests. Production sets audit
 * address to zero. Private Aq/Sa residency uses destination_stride control
 * and reserved[1..3] for first producer sequence and source FP identity. */
#define NX_LINEAR_ABI 0x4c4e3135u
#define NX_LINEAR_STAGE_M 4u
#define NX_LINEAR_MAX_K 4864u
#define NX_LINEAR_MAX_G 76u
struct nx_linear_audit { int32_t dot; float activation_product, value, partial; };
#endif
