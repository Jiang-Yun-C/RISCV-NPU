// Copyright 2024 Google LLC
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

// PDS portable SRAM: same generic SYNTHESIS branch as locked upstream.
// Also used in T24 VCS execution, so there is no DPI-only qualification path.
module Sram #(parameter NUM_ENTRIES=128, GLOBAL_BASE_ADDR=0)(
  input clock, enable, write,
  input [$clog2(NUM_ENTRIES)-1:0] addr,
  input [127:0] wdata,
  input [15:0] wmask,
  output [127:0] rdata,
  output rvalid);
  reg [127:0] mem[0:NUM_ENTRIES-1];
  reg [$clog2(NUM_ENTRIES)-1:0] raddr;
  reg rvalid_reg;
  assign rdata=mem[raddr];
  assign rvalid=rvalid_reg;
  always @(posedge clock) begin
    rvalid_reg<=enable;
    for(integer i=0;i<16;i=i+1)
      if(enable && write && wmask[i]) mem[addr][8*i+:8]<=wdata[8*i+:8];
    if(enable && !write) raddr<=addr;
  end
endmodule
