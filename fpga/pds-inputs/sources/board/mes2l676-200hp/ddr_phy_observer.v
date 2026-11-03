// Observe the HMIC 1.3 exported debug buses in their core/sysclk domain.
// The reset is the board/core reset, so PHY training retries retain evidence.
module ddr_phy_observer (
  input clk, rst_n,
  input [31:0] flags, errors, write_beats, read_beats, aw_count, ar_count,
  input [29:0] calib,
  input [31:0] aux,
  input [67:0] slice_status,
  input [87:0] slice_state,
  input [263:0] slice_data,
  output reg [2047:0] report
);
  reg [63:0] cycles, first_cycles;
  reg [15:0] main_seen;
  reg [31:0] rd_seen, transitions;
  reg [13:0] sticky_errors;
  reg first_valid;
  reg [5:0] first_retry, retry_d;
  reg [29:0] first_calib, last_retry_calib;
  reg [31:0] first_aux;
  reg [67:0] first_status;
  reg [87:0] first_state;
  reg [263:0] first_data;
  reg [3:0] main_d;
  wire [3:0] main_state = calib[29:26];
  wire [4:0] rd_state = calib[17:13];
  // Packed HMIC slice_status: 17 groups of four lane bits, lane 0 low.
  wire [13:0] fault = {flags[30],calib[0],slice_status[51:48],
                       slice_status[35:32],slice_status[67:64]};
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      cycles<=0; first_cycles<=0; main_seen<=0; rd_seen<=0;
      transitions<=0; sticky_errors<=0; first_valid<=0; first_retry<=0;
      first_calib<=0; first_aux<=0; first_status<=0; first_state<=0;
      first_data<=0; main_d<=0; retry_d<=0; last_retry_calib<=0;
    end else begin
      cycles<=cycles+1'b1;
      main_seen<=main_seen | (16'b1 << main_state);
      rd_seen<=rd_seen | (32'b1 << rd_state);
      sticky_errors<=sticky_errors | fault;
      main_d<=main_state; retry_d<=flags[29:24];
      if (main_d!=main_state) transitions<=transitions+1'b1;
      if (retry_d!=flags[29:24]) last_retry_calib<=calib;
      if (!first_valid && |fault) begin
        first_valid<=1; first_retry<=flags[29:24]; first_cycles<=cycles;
        first_calib<=calib; first_aux<=aux; first_status<=slice_status;
        first_state<=slice_state; first_data<=slice_data;
      end
    end
  end
  // 64 little-endian words; words 0/1 are filled by the UART at snapshot time.
  always @(*) begin
    report=0;
    report[2*32+:32]=flags; report[3*32+:32]=errors;
    report[4*32+:32]=write_beats; report[5*32+:32]=read_beats;
    report[6*32+:32]=aw_count; report[7*32+:32]=ar_count;
    report[8*32+:64]=cycles;
    report[10*32+:32]={16'b0,main_seen}; report[11*32+:32]=rd_seen;
    report[12*32+:32]={18'b0,sticky_errors};
    report[13*32+:32]={18'b0,first_retry,7'b0,first_valid};
    report[14*32+:64]=first_cycles;
    report[16*32+:32]={2'b0,first_calib}; report[17*32+:32]=first_aux;
    report[18*32+:96]={28'b0,first_status};
    report[21*32+:96]={8'b0,first_state};
    report[24*32+:288]={24'b0,first_data};
    report[33*32+:32]={2'b0,calib}; report[34*32+:32]=aux;
    report[35*32+:96]={28'b0,slice_status};
    report[38*32+:96]={8'b0,slice_state};
    report[41*32+:288]={24'b0,slice_data};
    report[50*32+:32]=transitions;
    report[51*32+:32]={2'b0,last_retry_calib};
  end
endmodule
