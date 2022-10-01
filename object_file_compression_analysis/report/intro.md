# homcc: Compression Algorithm Investigation

## Problem Statement

- Compiled object files (.o) need to be sent to the client.
- We can only transfer a limited number of bytes in a second.
- The bandwidth is dependent on the client.
    - 6000 Kbps – very poor 
    - 55 Mbps – average in Germany
    - 10,000 Mbps – in-office 
- Size of the data can be reduced by compressing before sending.
- But, compression also takes time and its strength can be adjusted.
- Given different compression algorithms and bandwidths, how do we hit the sweet spot between compression/transfer?

- We want to minimize the overall time for sending the files. How do we define the overall time?
    - consecutive: first compress the file, then send it.
    `time = compression_time + (filesize-reduction) ÷ bandwidth`
    - streamed: compress and send simultaneously.
    `time = max{compression_time, (filesize-reduction) ÷ bandwidth}`
