// 64 KiB synchronous 128-bit SRAM. S0 serializes DMA and control accesses;
// the two logical owners share one physical byte-enable port. No data reset.
module nx_ce64_scratch #(parameter bit PREDICATE_METADATA=0,
    parameter bit B_PRECOMPUTED_PREDICATES=0,
    parameter bit SCALE_METADATA=0,
    parameter bit B_PRECOMPUTED_SCALE_PREDICATES=0) (
  input logic clk,
  input logic a_en, b_en,
  input logic [11:0] a_addr, b_addr,
  input logic [15:0] a_we, b_we,
  input logic [127:0] a_data, b_data,
  input wire [15:0] b_min80,b_nonzero,
  input wire [15:0] b_scale_zero,b_scale_lo0,b_scale_lo1,
  output logic [127:0] a_q, b_q,
  output wire [15:0] min80_q, nonzero_q,
  output wire [15:0] scale_zero_q,scale_lo0_q,scale_lo1_q
);
  wire en=a_en||b_en;
  wire [11:0] address=b_en ? b_addr : a_addr;
  wire [15:0] mask=b_en ? b_we : a_we;
  wire [127:0] data=b_en ? b_data : a_data;
  wire [127:0] q;
  assign a_q=q;
  assign b_q=q;
  // Equal-capacity byte layout, one shared address/en/owner and no data reset.
  genvar lane;
  generate for(lane=0;lane<16;lane=lane+1)begin:byte_lanes
    logic [7:0] ram [0:4095];
    logic [7:0] byte_q;
    assign q[8*lane+:8]=byte_q;
    always_ff @(posedge clk) begin
      if(en) begin
        byte_q <= ram[address];
        if(mask[lane]) ram[address] <= data[8*lane+:8];
      end
    end
    if(PREDICATE_METADATA)begin: byte_predicates
      // Match the data RAM's read-before-write behavior, write mask and hold
      // edge. No reset, extra read, address or payload capacity is introduced.
      // Store the procedural-if projection: only a known true comparison is
      // an error predicate, including partially known four-state bytes.
      localparam META_BITS=SCALE_METADATA ? 5 : 2;
      logic [META_BITS-1:0] ram [0:4095];
      logic [META_BITS-1:0] predicates;
      logic [1:0] write_predicates;
      logic [2:0] write_scale_predicates;
      if(SCALE_METADATA)begin: exact_scale_predicates
        logic [2:0] a_scale_predicates;
        always_comb begin
          a_scale_predicates[0]=(a_data[8*lane+:8]==8'b0);
          a_scale_predicates[1]=!a_data[8*lane+7] && (a_data[8*lane+:7]!=7'b0);
          a_scale_predicates[2]=!a_data[8*lane+7] && (a_data[8*lane+:7]!=7'h7f);
          if(B_PRECOMPUTED_SCALE_PREDICATES && ((b_en^b_en)===1'b0))
            write_scale_predicates=b_en ?
              {b_scale_lo1[lane],b_scale_lo0[lane],b_scale_zero[lane]} : a_scale_predicates;
          else begin
            // Unknown owner must classify the original merged payload.
            // Logical equality/inequality preserve its partially known X/Z.
            write_scale_predicates[0]=(data[8*lane+:8]==8'b0);
            write_scale_predicates[1]=!data[8*lane+7] && (data[8*lane+:7]!=7'b0);
            write_scale_predicates[2]=!data[8*lane+7] && (data[8*lane+:7]!=7'h7f);
          end
        end
        assign scale_zero_q[lane]=predicates[2];
        assign scale_lo0_q[lane]=predicates[3];
        assign scale_lo1_q[lane]=predicates[4];
      end else begin: uncached_scale_predicates
        assign write_scale_predicates=0;
        assign scale_zero_q[lane]=(byte_q==8'b0);
        assign scale_lo0_q[lane]=!byte_q[7] && (byte_q[6:0]!=7'b0);
        assign scale_lo1_q[lane]=!byte_q[7] && (byte_q[6:0]!=7'h7f);
      end
      if(B_PRECOMPUTED_PREDICATES)begin: precomputed_b
        logic [1:0] a_predicates;
        always_comb begin
          a_predicates=0;
          if(a_data[8*lane+:8]==8'h80)a_predicates[0]=1'b1;
          if(a_data[8*lane+:8]!=0)a_predicates[1]=1'b1;
          if((b_en^b_en)===1'b0)
            write_predicates=b_en ? {b_nonzero[lane],b_min80[lane]} : a_predicates;
          else begin
            // Classification does not commute with a four-state owner mux.
            // Keep the exact original merge-then-procedural-if projection.
            write_predicates=0;
            if(data[8*lane+:8]==8'h80)write_predicates[0]=1'b1;
            if(data[8*lane+:8]!=0)write_predicates[1]=1'b1;
          end
        end
      end else begin: original_predicates
        always_comb begin
          write_predicates=0;
          if(data[8*lane+:8]==8'h80)write_predicates[0]=1'b1;
          if(data[8*lane+:8]!=0)write_predicates[1]=1'b1;
        end
      end
      assign min80_q[lane]=predicates[0];
      assign nonzero_q[lane]=predicates[1];
      always_ff @(posedge clk)begin
        if(en)begin
          predicates<=ram[address];
          if(mask[lane])begin
            if(SCALE_METADATA)ram[address]<={write_scale_predicates,write_predicates};
            else ram[address]<=write_predicates;
          end
        end
      end
    end else begin: uncached_predicates
      assign min80_q[lane]=(byte_q==8'h80);
      assign nonzero_q[lane]=(byte_q!=0);
      assign scale_zero_q[lane]=(byte_q==8'b0);
      assign scale_lo0_q[lane]=!byte_q[7] && (byte_q[6:0]!=7'b0);
      assign scale_lo1_q[lane]=!byte_q[7] && (byte_q[6:0]!=7'h7f);
    end
  end endgenerate
`ifndef SYNTHESIS
  assert property(@(posedge clk) !(a_en&&b_en)) else $fatal(1,"S0 scratch ownership collision");
`endif
endmodule
