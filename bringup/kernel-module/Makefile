obj-m := msgdma_userio.o
msgdma_userio-y += msgdma_userio_platform.o  msgdma_userio_chr.o

SRC := $(shell pwd)

all:
	$(MAKE) -C $(KERNEL_SRC) M=$(SRC) modules

clean:
	$(MAKE) -C $(KERNEL_SRC) M=$(SRC) clean
