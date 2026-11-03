#ifndef NX_CORAL_STREAM_H
#define NX_CORAL_STREAM_H
#include <stdint.h>

/* Private Coral microprogram ABI; never serialize nx_context or nx_tensor. */
#define NX_STREAM_ABI 0x53543134u
#define NX_STREAM_COPY 1u
#define NX_STREAM_LINEAR 2u
#define NX_STREAM_ROWS 128u
#define NX_STREAM_CHUNK 64u
struct nx_stream_request {
    uint32_t abi, size, session_lo, session_hi, sequence_lo, sequence_hi;
    uint32_t opcode, m, n, k, source, destination, scales, bias;
    uint32_t aq, sa, output_stride, row_bytes, source_stride, destination_stride;
    uint32_t reserved[4];
};
struct nx_stream_result {
    uint32_t abi, size, session_lo, session_hi, sequence_lo, sequence_hi;
    int32_t status;
    uint32_t valid, tiles, rows, checksum, reserved;
    uint64_t payload_read, payload_write, cycles, load_cycles, compute_cycles;
    uint64_t write_cycles, other_cycles;
};
#endif
