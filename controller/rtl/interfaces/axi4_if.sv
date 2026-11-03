// Shared logical SoC memory boundary. No simulation state or vendor DDR signals.
interface axi4_if #(parameter DATA_W=32, ID_W=4) (input logic aclk);
    logic [31:0] awaddr, araddr;
    logic [ID_W-1:0] awid, arid, bid, rid;
    logic [7:0] awlen, arlen;
    logic [2:0] awsize, arsize;
    logic [1:0] awburst, arburst, bresp, rresp;
    logic awvalid, awready, wvalid, wready, wlast;
    logic bvalid, bready, arvalid, arready, rvalid, rready, rlast;
    logic [DATA_W-1:0] wdata, rdata;
    logic [DATA_W/8-1:0] wstrb;
    modport master (input awready,wready,bvalid,bresp,bid,arready,rvalid,rresp,rid,rdata,rlast,
        output awaddr,awid,awlen,awsize,awburst,awvalid,wdata,wstrb,wlast,wvalid,bready,
        araddr,arid,arlen,arsize,arburst,arvalid,rready);
    modport slave (input awaddr,awid,awlen,awsize,awburst,awvalid,wdata,wstrb,wlast,wvalid,
        bready,araddr,arid,arlen,arsize,arburst,arvalid,rready,
        output awready,wready,bvalid,bresp,bid,arready,rvalid,rresp,rid,rdata,rlast);
endinterface
