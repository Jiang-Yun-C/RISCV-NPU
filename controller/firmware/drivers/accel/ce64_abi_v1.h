#ifndef NX_CE64_ABI_V1_H
#define NX_CE64_ABI_V1_H
/* CE64 transport ABI. Qualification is recorded separately. Fixed little-endian
 * words on MMIO; do not memcpy this into a different-endian machine's device.
 * Body fields mirror frozen stream.h, not a claim of Coral ELF compatibility. */
#include <stdint.h>
#include <stddef.h>
#define CE64_DESC_MAGIC UINT32_C(0x34364543) /* little-endian "CE64" */
#define CE64_RESULT_MAGIC UINT32_C(0x52364543)
#define CE64_ABI_VERSION UINT32_C(1)
#define CE64_NUMERIC_PROFILE UINT32_C(1) /* w8a8-g64-fp32-v1 + frozen manifest */
#define CE64_LINEAR_ABI UINT32_C(0x4c4e3135)
#define CE64_LINEAR_OPCODE UINT32_C(2)
#define CE64_MMIO_BASE UINT32_C(0x10003000) /* CE64 map v2 */
#define CE64_FLAG_AUDIT UINT32_C(1)
#define CE64_PROFILE_SERIAL UINT32_C(0)
#define CE64_PROFILE_BURST UINT32_C(1) /* do NOT advertise until separately qualified */
#define CE64_ID 0x000u
#define CE64_VERSION 0x004u
#define CE64_CAPS 0x008u
#define CE64_STATUS 0x00cu
#define CE64_CONTROL 0x010u
#define CE64_IRQ_STATUS 0x014u
#define CE64_IRQ_MASK 0x018u
#define CE64_EPOCH 0x01cu
#define CE64_DOORBELL 0x020u
#define CE64_ACCEPT_GENERATION 0x024u
#define CE64_ACK 0x028u
#define CE64_FIRST_FAULT_ADDRESS 0x02cu
#define CE64_RUN_LIMIT_LO 0x030u
#define CE64_RUN_LIMIT_HI 0x034u
#define CE64_DRAIN_LIMIT_LO 0x038u
#define CE64_DRAIN_LIMIT_HI 0x03cu
#define CE64_RESET_STATUS 0x040u
#define CE64_EXECUTION_PROFILE 0x044u
#define CE64_IRQ_GENERATION 0x048u
#define CE64_TRANSPORT_DIAGNOSTIC 0x04cu
#define CE64_DESC_WRITTEN_BITMAP 0x050u
#define CE64_OUTSTANDING 0x054u
/* Board-internal physical boot initialization, never a public operator bit. */
#define CE64_PRIVATE_STARTUP_ZERO_OPCODE UINT32_C(4)
#define CE64_STARTUP_STATUS 0x058u
#define CE64_CLEAR_SHADOW 0x060u
#define CE64_PERF_SNAPSHOT 0x070u
#define CE64_PERF_BASE 0x080u
/* Private CPU -> PV probability window. This capability describes storage,
 * independently of the public profile qualification mask at CE64_CAPS. */
#define CE64_LONG_PV_CAPABILITY 0x130u
#define CE64_LONG_PV_MAGIC UINT32_C(0x50563531)
#define CE64_HEAD_ARGMAX_CAPABILITY 0x134u
#define CE64_HEAD_ARGMAX_MAGIC UINT32_C(0x414d5831)
#define CE64_HEAD_ARGMAX_BASE 0x140u
#define CE64_P_WINDOW_BEGIN 0x100u
#define CE64_P_WINDOW_WORDS 0x104u
#define CE64_P_WINDOW_SESSION_LO 0x108u
#define CE64_P_WINDOW_SESSION_HI 0x10cu
#define CE64_P_WINDOW_SEQUENCE_LO 0x110u
#define CE64_P_WINDOW_SEQUENCE_HI 0x114u
#define CE64_P_WINDOW_PUBLISH 0x118u
#define CE64_P_WINDOW_STATUS 0x11cu
#define CE64_P_WINDOW_LENGTH 0x120u
#define CE64_P_WINDOW_CAPABILITY 0x124u
#define CE64_P_WINDOW_PADDED 0x128u
/* Private scratch lease storage; this is not a public qualified profile. */
#define CE64_AQSA_CAPABILITY 0x12cu
#define CE64_AQSA_MAGIC UINT32_C(0x41515331)
#define CE64_AQSA_PRODUCER UINT32_C(0xa3510000)
#define CE64_AQSA_CONSUMER UINT32_C(0xa3520000)
#define CE64_P_WINDOW_MAGIC UINT32_C(0x50574231)
#define CE64_P_WINDOW_READY (1u<<0)
#define CE64_P_WINDOW_LOCKED (1u<<1)
#define CE64_P_WINDOW_DATA 0x800u
#define CE64_P_WINDOW_CAPACITY_WORDS 512u
#define CE64_P_WINDOW_LOCAL UINT32_C(1) /* opcode5 destination_stride */
#define CE64_DESCRIPTOR_SHADOW 0x200u
#define CE64_COMPLETION_BANK0 0x400u
#define CE64_COMPLETION_BANK1 0x500u
/* CONTROL: level isolate, level run-enable, edge request reset. RESET is NOT
 * an asynchronous wire to AXI/DDR. The drain coordinator may reject it. */
#define CE64_CTL_RUN_ENABLE (1u<<0)
#define CE64_CTL_ISOLATE (1u<<1)
#define CE64_CTL_RESET_REQUEST (1u<<2)
#define CE64_ST_IDLE (1u<<0)
#define CE64_ST_RUNNING (1u<<1)
#define CE64_ST_ISOLATE (1u<<2)
#define CE64_ST_DRAINED (1u<<3)
#define CE64_ST_COMPLETION_PENDING (1u<<4)
#define CE64_ST_FAULTED (1u<<5)
#define CE64_ST_READY_SUBMIT (1u<<6)
#define CE64_ST_COMPLETION_BANK (1u<<7)
struct ce64_linear_request {
 uint32_t abi,size,session_lo,session_hi,sequence_lo,sequence_hi;
 uint32_t opcode,m,n,k,source,destination,scales,bias;
 uint32_t aq,sa,output_stride,row_bytes,source_stride,destination_stride;
 uint32_t reserved[4];
};
struct ce64_linear_result {
 uint32_t abi,size,session_lo,session_hi,sequence_lo,sequence_hi;
 int32_t status;
 uint32_t valid,tiles,rows,checksum,reserved;
 uint64_t payload_read,payload_write,cycles,load_cycles,compute_cycles;
 uint64_t write_cycles,other_cycles;
};
struct ce64_descriptor {
 uint32_t magic,version,bytes,flags;
 uint32_t epoch,numeric_profile,reserved0,reserved1;
 struct ce64_linear_request body;
};
struct ce64_completion {
 uint32_t magic,version,bytes,epoch;
 uint32_t backend_id,execution_profile,first_fault_address,private_diagnostic;
 struct ce64_linear_result body;
 uint32_t internal_fault_code,fault_kind,diagnostic_snapshot_tag,reserved0;
 uint32_t descriptor_generation,commit_generation; /* commit written LAST */
};
struct ce64_group_audit { int32_t dot; uint32_t p_bits,v_bits,partial_bits; };
_Static_assert(sizeof(struct ce64_linear_request)==96,"request size");
_Static_assert(sizeof(struct ce64_linear_result)==104,"result size");
_Static_assert(offsetof(struct ce64_descriptor,body)==32,"descriptor body");
_Static_assert(sizeof(struct ce64_descriptor)==128,"descriptor size");
_Static_assert(offsetof(struct ce64_completion,body)==32,"completion body");
_Static_assert(offsetof(struct ce64_completion,commit_generation)==156,"commit offset");
_Static_assert(sizeof(struct ce64_completion)==160,"completion size");
_Static_assert(sizeof(struct ce64_group_audit)==16,"audit size");
#endif
