module simple_fifo_checker (
  input logic clk,
  input logic rst_n,
  input logic full,
  input logic empty
);
  a_flags_mutually_exclusive: assert property (
    @(posedge clk) disable iff (!rst_n) !(full && empty)
  ) else $error("FIFO full and empty flags are both asserted");
endmodule
