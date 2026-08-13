module simple_fifo_harness;
  localparam int DATA_WIDTH = 8;
  localparam int DEPTH = 4;

  logic clk = 1'b0;
  logic rst_n = 1'b0;
  simple_fifo_if #(.DATA_WIDTH(DATA_WIDTH)) fifo_if (clk, rst_n);

  always #5 clk = ~clk;

  simple_fifo #(.DATA_WIDTH(DATA_WIDTH), .DEPTH(DEPTH)) u_dut (
    .clk        (fifo_if.clk),
    .rst_n      (fifo_if.rst_n),
    .push       (fifo_if.push),
    .write_data (fifo_if.write_data),
    .full       (fifo_if.full),
    .pop        (fifo_if.pop),
    .read_data  (fifo_if.read_data),
    .empty      (fifo_if.empty)
  );

  task automatic push_byte(input logic [DATA_WIDTH-1:0] value);
    @(negedge clk);
    if (fifo_if.full) $fatal(1, "push attempted while full");
    fifo_if.push = 1'b1;
    fifo_if.write_data = value;
    @(negedge clk);
    fifo_if.push = 1'b0;
  endtask

  task automatic pop_and_check(input logic [DATA_WIDTH-1:0] expected);
    @(negedge clk);
    if (fifo_if.empty) $fatal(1, "pop attempted while empty");
    if (fifo_if.read_data !== expected) begin
      $fatal(1, "read mismatch: expected %0h got %0h", expected, fifo_if.read_data);
    end
    fifo_if.pop = 1'b1;
    @(negedge clk);
    fifo_if.pop = 1'b0;
  endtask

  initial begin
    fifo_if.push = 1'b0;
    fifo_if.pop = 1'b0;
    fifo_if.write_data = '0;
    repeat (2) @(negedge clk);
    rst_n = 1'b1;
    repeat (1) @(negedge clk);

    if (!fifo_if.empty) $fatal(1, "FIFO not empty after reset");
    push_byte(8'h12);
    push_byte(8'h34);
    pop_and_check(8'h12);
    pop_and_check(8'h34);
    @(negedge clk);
    if (!fifo_if.empty) $fatal(1, "FIFO not empty after smoke sequence");
    $display("SIMPLE_FIFO_SMOKE PASS");
    $finish;
  end
endmodule
