interface simple_fifo_if #(parameter int DATA_WIDTH = 8) (input logic clk, rst_n);
  logic push;
  logic [DATA_WIDTH-1:0] write_data;
  logic full;
  logic pop;
  logic [DATA_WIDTH-1:0] read_data;
  logic empty;

  modport dut_mp (
    input clk, rst_n, push, write_data, pop,
    output full, read_data, empty
  );

  modport test_mp (
    input clk, rst_n, full, read_data, empty,
    output push, write_data, pop
  );
endinterface
