bind simple_fifo simple_fifo_checker u_simple_fifo_checker (
  .clk   (clk),
  .rst_n (rst_n),
  .full  (full),
  .empty (empty)
);
