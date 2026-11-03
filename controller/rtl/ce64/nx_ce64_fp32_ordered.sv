// Single row accumulator. p/v may be prepared ahead; only one dependent ADD
// is in flight. The next ADD uses the preceding hardware partial on retirement.
// reset_n resets local arithmetic only; SoC soft reset must first drain it.
module nx_ce64_fp32_ordered (
  input logic clock, reset_n, req_valid_i,
  output logic req_ready_o,
  input logic signed [31:0] dot_i,
  input logic [31:0] sa_i, sw_i, initial_acc_i, tag_i, epoch_i,
  input logic first_i, last_i,
  input logic [3:0] status_i,
  output logic rsp_valid_o,
  input logic rsp_ready_i,
  output logic [31:0] p_o, v_o, partial_o, tag_o, epoch_o,
  output logic last_o, idle_o,
  output logic [3:0] status_o,
  output logic [4:0] flags_o
);
  import nx_ce64_math_pkg::*;
  typedef struct packed {
    logic [31:0] sw, initial_acc;
    logic first, last;
    logic [3:0] status;
  } m1_aux_t;
  typedef struct packed {
    logic [31:0] p, initial_acc;
    logic first, last;
    logic [3:0] status;
    logic [4:0] flags;
  } m2_aux_t;
  typedef struct packed {
    logic [31:0] p, v;
    logic last;
    logic [3:0] status;
    logic [4:0] flags;
  } add_aux_t;
  m1_aux_t a1;
  m2_aux_t a2, in2;
  add_aux_t a3, in3;
  logic r1, valid1, r2, valid2, ra, va;
  logic row_open, row_sealed, add_busy;
  logic [31:0] accumulator, row_epoch, add_acc;
  logic [3:0] row_status, effective_status, request_status;
  logic [31:0] p, v;
  logic [63:0] t1, t2, t3;
  logic [4:0] f1, f2, f3;
  logic take_result, issue_add;
  logic [2:0] pending_groups;
  logic credit;

  assign idle_o = !row_open && pending_groups==0;
  // The physical FP pipes have more registers than live row contexts. Limit
  // accepted preparations to the four credits allowed by the S0 contract.
  assign credit = pending_groups < 4 || take_result;
  assign req_ready_o = reset_n && !row_sealed && credit && r1;
  always_comb begin
    request_status = status_i;
    if (request_status == OK &&
        ((first_i == row_open) || (row_open && epoch_i != row_epoch)))
      request_status = BAD_PROTOCOL;
    if (request_status == OK)
      request_status = input_status(dot_i, sa_i, sw_i, first_i ? initial_acc_i : 32'b0);
  end
  nx_ce64_fp32_op #(.MUL(1), .AUX_W($bits(m1_aux_t))) mul_p (
    .clock, .reset_n, .a_i(cast_dot(dot_i)), .b_i(sa_i),
    .tag_i({epoch_i,tag_i}),
    // A malformed repeated FIRST records an error, without resetting the
    // accumulator of the row already in flight.
    .aux_i({sw_i,initial_acc_i,!row_open,last_i,request_status}),
    .valid_i(req_valid_i && !row_sealed && credit), .ready_o(r1),
    .result_o(p), .flags_o(f1), .tag_o(t1), .aux_o(a1),
    .valid_o(valid1), .ready_i(r2));
  assign in2 = '{p:p, initial_acc:a1.initial_acc, first:a1.first, last:a1.last,
    status:(a1.status == OK && !finite32(p) ? NONFINITE_P : a1.status), flags:f1};
  nx_ce64_fp32_op #(.MUL(1), .AUX_W($bits(m2_aux_t))) mul_v (
    .clock, .reset_n, .a_i(p), .b_i(a1.sw), .tag_i(t1), .aux_i(in2),
    .valid_i(valid1), .ready_o(r2), .result_o(v), .flags_o(f2),
    .tag_o(t2), .aux_o(a2), .valid_o(valid2), .ready_i(issue_add));

  assign take_result = rsp_valid_o && rsp_ready_i;
  // Bypass the retiring partial; never supply an old request-time acc snapshot.
  assign add_acc = a2.first ? a2.initial_acc : (take_result ? partial_o : accumulator);
  assign effective_status = take_result ? status_o : row_status;
  assign in3 = '{p:a2.p, v:v, last:a2.last,
    status:(effective_status != OK ? effective_status :
      (a2.status == OK && !finite32(v) ? NONFINITE_V : a2.status)), flags:(a2.flags | f2)};
  assign issue_add = reset_n && (!add_busy || take_result) && ra;
  nx_ce64_fp32_op #(.MUL(0), .AUX_W($bits(add_aux_t))) add (
    .clock, .reset_n, .a_i(add_acc), .b_i(v), .tag_i(t2), .aux_i(in3),
    .valid_i(valid2 && (!add_busy || take_result)), .ready_o(ra),
    .result_o(partial_o), .flags_o(f3), .tag_o(t3), .aux_o(a3),
    .valid_o(va), .ready_i(rsp_ready_i));
  assign rsp_valid_o = reset_n && va;
  assign p_o=a3.p;
  assign v_o=a3.v;
  assign last_o=a3.last;
  assign tag_o=t3[31:0];
  assign epoch_o=t3[63:32];
  assign flags_o=a3.flags | f3;
  assign status_o=a3.status == OK && !finite32(partial_o) ? NONFINITE_SUM : a3.status;
  always_ff @(posedge clock or negedge reset_n) begin
    if (!reset_n) begin
      row_open<=0; row_sealed<=0; add_busy<=0;
      pending_groups<=0;
      accumulator<=0; row_epoch<=0; row_status<=OK;
    end else begin
      case ({req_valid_i && req_ready_o,take_result})
        2'b10:pending_groups<=pending_groups+1'b1;
        2'b01:pending_groups<=pending_groups-1'b1;
        default:;
      endcase
      if (req_valid_i && req_ready_o) begin
        row_open<=1;
        if (!row_open) row_epoch<=epoch_i;
        if (last_i) row_sealed<=1;
      end
      if (take_result) begin
        accumulator<=partial_o;
        row_status<=status_o;
        add_busy<=0;
        if (last_o) begin
          row_open<=0; row_sealed<=0; row_status<=OK;
        end
      end
      if (valid2 && issue_add) add_busy<=1;
    end
  end
endmodule
