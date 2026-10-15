/* SPDX-License-Identifier: BSD-3-Clause */
/*
 * Char device for the msgdma_userio driver
 *
 * Copyright (C) 2022 Intel Corporation, Inc.
 *
 * Authors:
 *   Richard Davies <richard.davies@intel.com>
 */
#include <linux/kernel.h>
#include <linux/module.h>
#include <linux/device.h>
#include <linux/slab.h>
#include <linux/fs.h>
#include <linux/idr.h>

#include <linux/dma-mapping.h>
#include <linux/dmaengine.h>

#include "msgdma_userio_chr.h"

static DEFINE_IDA(msgdma_userio_ida);
static struct msgdma_userio_global_ctx gctx;

struct msgdma_userio_flip_ctx {
    struct msgdma_userio_chr_dev_ctx *ctx;
    uint64_t fpga_offset;
};

static int msgdma_userio_open(struct inode *inode, struct file *flip)
{
    int ret = 0;
    struct msgdma_userio_flip_ctx *fctx;
    struct msgdma_userio_chr_dev_ctx *dctx;

    dctx = container_of(inode->i_cdev, struct msgdma_userio_chr_dev_ctx,
                msgdma_userio_cdev);
    if (unlikely(dctx == NULL)) {
        pr_warn("msgdma_userio_open: failed to retreive msgdma_userio_chr_dev_ctx.\n");
        ret = -EFAULT;
        goto fail;
    }

    fctx = kzalloc(sizeof(struct msgdma_userio_flip_ctx), GFP_KERNEL);
    if (unlikely(fctx == NULL)) {
        pr_warn("msgdma_userio_open: failed to allocate msgdma_userio_flip_ctx.\n");
        ret = -ENOMEM;
        goto fail;
    }

    fctx->ctx = dctx;

    flip->private_data = fctx;

fail:
    return ret;
}

static int msgdma_userio_release(struct inode *inode, struct file *flip)
{
    struct msgdma_userio_flip_ctx *fctx;

    fctx = flip->private_data;
    if (unlikely(fctx == NULL)) {
        pr_warn("msgdma_userio_release: Invalid fctx\n");
        return -EFAULT;
    }

    kfree(fctx);
    flip->private_data = NULL;

    return 0;
}

struct io_mapped_buffer {
    int mapped_pages;
    uint32_t first_offset;
    struct page **pages;
    struct sg_table sg_table;

    int mapped_nents;
    int direction;
};

int prepare_user_buffer(struct device *dev, const char __user *buf,
            const size_t count, const int direction,
            struct io_mapped_buffer *ctx)
{
    int status = 0;
    uintptr_t addr = (uintptr_t)buf;
    unsigned long start_page = PFN_DOWN(addr) << PAGE_SHIFT;
    unsigned long last_page = PFN_DOWN(addr + count - 1) << PAGE_SHIFT;
    /* Calculate the number of required pages */
    uint32_t num_pages =
        (last_page >> PAGE_SHIFT) - (start_page >> PAGE_SHIFT) + 1;

    ctx->first_offset = addr & ~PAGE_MASK;
    ctx->direction = direction;

    pr_debug(
        "start 0x%lx - end 0x%lx, buf 0x%p, 0x%lx, size %d, offset %d\n",
        start_page, last_page, buf, addr, (int)count,
        ctx->first_offset);
    /* Allocate for storage of the page structure */
    ctx->pages = kzalloc(num_pages * sizeof(struct page *), GFP_KERNEL);
    if (ctx->pages == NULL) {
        pr_warn("%s:%u: Failed to alloc ctx->pages\n", __func__,
               __LINE__);
        status = -ENOMEM;
        goto Error;
    }
    /* Map the pages */
    ctx->mapped_pages =
        get_user_pages_fast(start_page, num_pages, 1, ctx->pages);
    if (ctx->mapped_pages <= 0) {
        pr_warn("%s:%u: Failed get_user_pages_fast\n", __func__,
               __LINE__);
        status = -ENOMEM;
        goto Error;
    }
    pr_debug("ctx->mapped_pages %d\n", ctx->mapped_pages);

    status = sg_alloc_table_from_pages(&(ctx->sg_table), ctx->pages,
                       ctx->mapped_pages, ctx->first_offset,
                       count, GFP_KERNEL);
    if (status < 0) {
        pr_warn("%s:%u: Failed sg_alloc_table_from_pages\n", __func__,
               __LINE__);
        goto Error;
    }

    pr_debug("nents = %d, %d\n", (int)ctx->sg_table.nents,
         (int)ctx->mapped_pages);

    ctx->mapped_nents = dma_map_sg(dev, ctx->sg_table.sgl,
                       ctx->sg_table.nents, ctx->direction);
    if (ctx->mapped_nents == 0) {
        pr_warn("%s:%u: Failed dma_map_sg\n", __func__, __LINE__);
        status = -ENOMEM;
        goto Error;
    }
    return 0;

Error:
    if (ctx->pages) {
        kfree(ctx->pages);
        ctx->pages = NULL;
    }
    return status;
}

void unprepare_user_buffer(struct device *dev, struct io_mapped_buffer *ctx)
{
    pgoff_t pg;

    if (ctx->mapped_nents) {
        dma_unmap_sg(dev, ctx->sg_table.sgl, ctx->mapped_nents,
                 ctx->direction);
    }

    sg_free_table(&(ctx->sg_table));

    if (ctx->pages) {
        for (pg = 0; pg < ctx->mapped_pages; pg++) {
            put_page(ctx->pages[pg]);
        }

        kfree(ctx->pages);
        ctx->pages = NULL;
    }
}

int set_dma_emif_addr(struct dma_chan *dma,
              const struct msgdma_emif_region *emif_region,
              const loff_t *offp, const size_t count)
{
    struct dma_slave_config dma_config = { 0 };
    phys_addr_t emif_addr = emif_region->start_addr + *offp;
    uint32_t dma_align = ((1 << dma->device->copy_align) - 1);

    /* Check that we are setting up correct emif address */
    if (emif_addr < emif_region->start_addr) {
        pr_warn("%s:%u: set_dma_emif_addr\n", __func__, __LINE__);
        return -EINVAL;
    }
    if ((emif_addr + count) >= emif_region->end_addr) {
        pr_warn("%s:%u: set_dma_emif_addr\n", __func__, __LINE__);
        return -EINVAL;
    }

    /* Check that the address and size as on the correct dma align */
    if (emif_addr & dma_align) {
        pr_warn("%s:%u: set_dma_emif_addr\n", __func__, __LINE__);
        return -EINVAL;
    }
    if (count & dma_align) {
        pr_warn("%s:%u: set_dma_emif_addr\n", __func__, __LINE__);
        return -EINVAL;
    }

    dma_config.src_addr = emif_addr;
    dma_config.dst_addr = emif_addr;
    return dmaengine_slave_config(dma, &dma_config);
}

int check_buffer_user_alignment(struct dma_chan *dma, const char __user *buf,
                const size_t count)
{
    uint32_t dma_align = ((1 << dma->device->copy_align) - 1);

    if ((uintptr_t)buf & dma_align) {
        pr_warn("%s:%u: check_buffer_user_alignment\n", __func__,
               __LINE__);
        return -EINVAL;
    }

    if (count & dma_align) {
        pr_warn("%s:%u: check_buffer_user_alignment\n", __func__,
               __LINE__);
        return -EINVAL;
    }
    return 0;
}

/*
 * Issue one dmaengine transfer per scatter-gather entry, stepping the EMIF
 * address as we go.
 *
 * dmaengine_prep_slave_sg() treats the device side as a fixed-address
 * peripheral: altera-msgdma builds every descriptor with cfg->src_addr /
 * cfg->dst_addr unchanged (altera-msgdma.c, msgdma_prep_slave_sg). That is
 * right for a FIFO, but our EMIF target is ordinary memory that has to advance
 * across entries. Passing the whole list only works when dma_map_sg() has
 * coalesced the buffer into a single entry, which is what happens when the
 * mSGDMA sits behind an IOMMU.
 *
 * This mSGDMA lives in the FPGA fabric behind F2SDRAM, outside the SMMU, so
 * any buffer spanning more than one physical page arrives as several entries.
 * Handing them over together made every descriptor write the same EMIF address
 * and silently corrupt the transfer -- round trips passed up to 1 KB and failed
 * from 4 KB up.
 *
 * Submitting one entry at a time keeps the per-descriptor fixed-address
 * semantics that altera-msgdma implements, while we advance the EMIF offset.
 *
 * BURST_ENABLE=0 (mandatory -- the Avalon-to-AXI4 bridge doesn't split bursts
 * crossing a 4 KB boundary, and AXI4 forbids that) makes the fabric issue one
 * 32-byte beat per AXI transaction. get_user_pages_fast()/sg_alloc_table_from_pages()
 * coalesce physically-contiguous pages into a single sg entry, so a large
 * buffer (e.g. DLA model weights) can arrive as one multi-MB entry -- too
 * slow at that rate to finish inside dma_sync_wait()'s hardcoded 5 s budget
 * (dmaengine.c). Chunk each entry to bound the wait per descriptor.
 */
#define MSGDMA_USERIO_MAX_CHUNK (256 * 1024)

static int msgdma_userio_xfer_sg(struct msgdma_userio_flip_ctx *ctx,
                 struct io_mapped_buffer *buffer,
                 const loff_t *offp, const size_t count,
                 enum dma_transfer_direction dir)
{
    struct dma_chan *dma = ctx->ctx->dma;
    struct scatterlist *sg;
    dma_cookie_t cookie = 0;
    loff_t emif_off = *offp;
    unsigned int i;
    int result;

    /*
     * One entry at a time: submit it, wait for it, then move on.
     *
     * The entries cannot all be queued up front. msgdma_start_transfer()
     * splices pending_list into active_list and copies only the head
     * descriptor (plus its tx_list) into the FIFO; when that completes, the
     * interrupt handler calls it again and finds pending_list empty, so any
     * independently submitted descriptor is stranded and the transfer times
     * out. altera-msgdma only chains descriptors built by a single prep call.
     *
     * Do not dmaengine_terminate_sync() between entries either. That runs
     * msgdma_reset(), a full engine reset asserting MSGDMA_CSR_CTL_RESET,
     * which is a heavy hammer to fire on a transfer that completed normally.
     * Reset belongs on the abort path only.
     */
    for_each_sg(buffer->sg_table.sgl, sg, buffer->mapped_nents, i) {
        size_t remaining = sg_dma_len(sg);
        dma_addr_t entry_addr = sg_dma_address(sg);

        if (remaining == 0) {
            continue;
        }

        /* Bound each descriptor's wait to MSGDMA_USERIO_MAX_CHUNK worth of
         * transfer time, regardless of how large the coalesced sg entry is.
         */
        while (remaining > 0) {
            struct dma_async_tx_descriptor *descriptor;
            struct scatterlist single;
            size_t len = min_t(size_t, remaining, MSGDMA_USERIO_MAX_CHUNK);

            /*
             * One-entry list aliasing this chunk. altera-msgdma only reads
             * sg_dma_address()/sg_dma_len() off it, so it needs no page.
             */
            sg_init_table(&single, 1);
            sg_dma_address(&single) = entry_addr;
            sg_dma_len(&single) = len;

            result = set_dma_emif_addr(dma, &ctx->ctx->emif_region,
                           &emif_off, len);
            if (result < 0) {
                goto terminate;
            }

            descriptor = dmaengine_prep_slave_sg(dma, &single, 1, dir,
                                 DMA_PREP_INTERRUPT);
            if (!descriptor) {
                pr_warn("Failed to prepare DMA descriptor\n");
                result = -EINVAL;
                goto terminate;
            }

            cookie = dmaengine_submit(descriptor);
            if (dma_submit_error(cookie)) {
                pr_warn("dma_submit_error failed\n");
                result = -EINVAL;
                goto terminate;
            }

            if (dma_sync_wait(dma, cookie) != DMA_COMPLETE) {
                pr_warn("DMA Failed at sg entry %u/%d len=%zu emif_off=%lld dma=0x%llx\n",
                    i, buffer->mapped_nents, len, (long long)emif_off,
                    (unsigned long long)entry_addr);
                result = -EINVAL;
                goto terminate;
            }

            emif_off += len;
            entry_addr += len;
            remaining -= len;
        }
    }

    return count;

terminate:
    dmaengine_terminate_sync(dma);
    return result;
}

static ssize_t msgdma_userio_read(struct file *filp, char __user *buf,
                  size_t count, loff_t *offp)
{
    struct io_mapped_buffer buffer = { 0 };
    int result;
    struct dma_chan *dma;
    struct msgdma_userio_flip_ctx *ctx = filp->private_data;
    dma = ctx->ctx->dma;

    pr_debug("%s:%u: Reading %zu bytes at position %lld from U0x%p/K0x%p\n",
         __func__, __LINE__, count, *offp, buf, buf);

    result = prepare_user_buffer(dma->device->dev, buf, count,
                     DMA_FROM_DEVICE, &buffer);
    if (result < 0) {
        pr_warn("%s:%u: Failed prepare_user_buffer\n", __func__,
               __LINE__);
        goto error;
    }

    result = check_buffer_user_alignment(dma, buf, count);
    if (result < 0) {
        goto error;
    }

    result = msgdma_userio_xfer_sg(ctx, &buffer, offp, count,
                       DMA_DEV_TO_MEM);
    if (result >= 0) {
        pr_debug("DMA Passed\n");
        *offp += count;
    }

error:
    unprepare_user_buffer(dma->device->dev, &buffer);

    return result;
}

static ssize_t msgdma_userio_write(struct file *filp, const char __user *buf,
                   size_t count, loff_t *offp)
{
    struct io_mapped_buffer buffer = { 0 };
    int result;
    struct dma_chan *dma;
    struct msgdma_userio_flip_ctx *ctx = filp->private_data;
    dma = ctx->ctx->dma;

    pr_debug("%s:%u: Writing %zu bytes at position %lld from U0x%p/K0x%p\n",
         __func__, __LINE__, count, *offp, buf, buf);

    result = prepare_user_buffer(dma->device->dev, buf, count,
                     DMA_TO_DEVICE, &buffer);
    if (result < 0) {
        pr_warn("%s:%u: Failed prepare_user_buffer\n", __func__,
               __LINE__);
        goto error;
    }

    result = check_buffer_user_alignment(dma, buf, count);
    if (result < 0) {
        goto error;
    }

    result = msgdma_userio_xfer_sg(ctx, &buffer, offp, count,
                       DMA_MEM_TO_DEV);
    if (result >= 0) {
        pr_debug("DMA passed\n");
        *offp += count;
    }

error:
    unprepare_user_buffer(dma->device->dev, &buffer);

    return result;
}

static loff_t msgdma_userio_llseek(struct file *flip, loff_t off, int whence)
{
    pr_debug("%s:%u: Seek %lld - %d\n", __func__, __LINE__, off, whence);
    if (unlikely(whence != SEEK_SET)) {
        return -ESPIPE;
    }
    flip->f_pos = off;
    return off;
}

static struct file_operations msgdma_userio_fops = {
    .owner = THIS_MODULE,
    .open = msgdma_userio_open,
    .release = msgdma_userio_release,
    .read = msgdma_userio_read,
    .write = msgdma_userio_write,
    .llseek = msgdma_userio_llseek
};

int msgdma_userio_chr_init(struct msgdma_userio_chr_dev_ctx **dctx,
               struct dma_chan *dma,
               const struct msgdma_emif_region emif_region,
               const char *device_name)
{
    struct msgdma_userio_chr_dev_ctx *cdev_ctx;
    int ret = 0;
    dev_t dev_num;

    cdev_ctx =
        kzalloc(sizeof(struct msgdma_userio_chr_dev_ctx), GFP_KERNEL);
    if (cdev_ctx == NULL) {
        return -ENOMEM;
    }

    /* Check we were given a dma channel */
    if (dma == NULL) {
        kfree(cdev_ctx);
        return -EINVAL;
    }
    cdev_ctx->dma = dma;
    cdev_ctx->emif_region = emif_region;

    cdev_ctx->major = MAJOR(gctx.device_number);
    cdev_ctx->minor = ida_alloc(&msgdma_userio_ida, GFP_KERNEL);
    if (cdev_ctx->minor < 0) {
        pr_warn("Failed to allocate minor number.\n");
        ret = cdev_ctx->minor;
        goto fail_cleanup;
    }

    dev_num = MKDEV(cdev_ctx->major, cdev_ctx->minor);
    cdev_init(&(cdev_ctx->msgdma_userio_cdev), &msgdma_userio_fops);
    cdev_ctx->msgdma_userio_cdev.owner = THIS_MODULE;

    ret = cdev_add(&(cdev_ctx->msgdma_userio_cdev), dev_num, 1);
    if (ret < 0) {
        pr_warn("cdev_add failed\n");
        goto fail_device;
    }
    cdev_ctx->msgdma_userio_device =
        device_create(gctx.gclass, NULL, dev_num, NULL, "%s",
                  device_name, cdev_ctx->minor);
    if (IS_ERR(cdev_ctx->msgdma_userio_device)) {
        ret = 0 - PTR_ERR(cdev_ctx->msgdma_userio_device);
        cdev_ctx->msgdma_userio_device = NULL;
        goto fail_device;
    }

    /* Return the new char device context */
    *dctx = cdev_ctx;

    pr_debug("Successfullt created char device\n");
    /* Success */
    return 0;

fail_device:
    cdev_del(&(cdev_ctx->msgdma_userio_cdev));

fail_cleanup:
    if (cdev_ctx->minor >= 0) {
        ida_free(&msgdma_userio_ida, cdev_ctx->minor);
    }
    kfree(cdev_ctx);
    *dctx = NULL;
    return ret;
}

void msgdma_userio_chr_exit(struct msgdma_userio_chr_dev_ctx *ctx)
{
    if (unlikely(ctx == NULL)) {
        pr_warn("Invalid device context\n");
        return;
    }

    if (ctx->msgdma_userio_device) {
        device_destroy(gctx.gclass, MKDEV(ctx->major, ctx->minor));
        ctx->msgdma_userio_device = NULL;
        ida_free(&msgdma_userio_ida, ctx->minor);
    }

    cdev_del(&(ctx->msgdma_userio_cdev));
}

/* create global context --> will be called from module init */
int msgdma_userio_global_chr_init(void)
{
    int ret;

    gctx.gclass = class_create(MSGDMA_USERIO_CLASS_NAME);
    if (IS_ERR(gctx.gclass)) {
        pr_warn("Failed to create driver class\n");
        return 0 - PTR_ERR(gctx.gclass);
    }

    ret = alloc_chrdev_region(&gctx.device_number, 0, MSGDMA_USERIO_MAX_DEV,
                  MSGDMA_USERIO_DRIVER_NAME);
    if (ret < 0) {
        pr_warn("Failed to allocate global chr context\n");
        return -1;
    }
    return 0;
}

/* must be called before module exits */
void msgdma_userio_global_chr_exit(void)
{
    class_destroy(gctx.gclass);
    gctx.gclass = NULL;
    unregister_chrdev_region(gctx.device_number, MSGDMA_USERIO_MAX_DEV);
}
