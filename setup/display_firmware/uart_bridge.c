#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/mman.h>
#include <sys/select.h>

#define UART_BASE 0x4a88000
#define TX_FIFO     0x700
#define RX_FIFO     0x780
#define TX_FIFO_ST  0x800
#define RX_FIFO_ST  0x804

volatile uint32_t *r;
static inline uint32_t rd(int o) { return r[o / 4]; }
static inline void wr(int o, uint32_t v) { r[o / 4] = v; }

int main(void) {
    int fd = open("/dev/mem", O_RDWR | O_SYNC);
    if (fd < 0) { perror("/dev/mem"); return 1; }
    void *map = mmap(NULL, 16384, PROT_READ|PROT_WRITE, MAP_SHARED, fd, UART_BASE & ~4095);
    if (map == MAP_FAILED) { perror("mmap"); close(fd); return 1; }
    r = (volatile uint32_t *)((uintptr_t)map + (UART_BASE & 4095));
    close(fd);

    fprintf(stderr, "tx_st=0x%08x rx_st=0x%08x\n", rd(TX_FIFO_ST), rd(RX_FIFO_ST));

    uint8_t buf[256];
    while (1) {
        fd_set fds; FD_ZERO(&fds); FD_SET(0, &fds);
        struct timeval tv = {0, 5000};
        if (select(1, &fds, NULL, NULL, &tv) < 0) break;
        if (FD_ISSET(0, &fds)) {
            int n = read(0, buf, sizeof(buf));
            if (n <= 0) break;
            for (int i = 0; i < n; i++) {
                while (!(rd(TX_FIFO_ST) & 1)) usleep(50);
                wr(TX_FIFO, buf[i]);
            }
        }
        while (rd(RX_FIFO_ST) & 1) {
            uint8_t ch = rd(RX_FIFO) & 0xFF;
            write(1, &ch, 1);
        }
    }
    return 0;
}
