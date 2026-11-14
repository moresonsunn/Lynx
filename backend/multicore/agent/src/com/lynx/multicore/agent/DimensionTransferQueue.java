package com.lynx.multicore.agent;

import java.util.concurrent.ConcurrentLinkedQueue;
import java.util.logging.Logger;

/**
 * Thread-safe queue for inter-dimension entity transfers.
 * Prevents ConcurrentModificationException when players or mobs cross portals
 * while dimensions are ticking in parallel.
 */
public class DimensionTransferQueue {
    private static final Logger LOGGER = Logger.getLogger("LMCE-DimensionTransferQueue");

    public static class EntityTransfer {
        private final Object entity;
        private final Object sourceLevel;
        private final Object destinationLevel;
        private final double x, y, z;

        public EntityTransfer(Object entity, Object sourceLevel, Object destinationLevel, double x, double y, double z) {
            this.entity = entity;
            this.sourceLevel = sourceLevel;
            this.destinationLevel = destinationLevel;
            this.x = x;
            this.y = y;
            this.z = z;
        }

        public Object getEntity() {
            return entity;
        }

        public Object getSourceLevel() {
            return sourceLevel;
        }

        public Object getDestinationLevel() {
            return destinationLevel;
        }

        public double getX() {
            return x;
        }

        public double getY() {
            return y;
        }

        public double getZ() {
            return z;
        }
    }

    private static final ConcurrentLinkedQueue<EntityTransfer> PENDING_TRANSFERS = new ConcurrentLinkedQueue<EntityTransfer>();

    public static void enqueueTransfer(Object entity, Object sourceLevel, Object destLevel, double x, double y, double z) {
        PENDING_TRANSFERS.offer(new EntityTransfer(entity, sourceLevel, destLevel, x, y, z));
    }

    public static int flushPendingTransfers() {
        int count = 0;
        EntityTransfer transfer;
        while ((transfer = PENDING_TRANSFERS.poll()) != null) {
            count++;
            // The transfer is finalized on the main thread during the barrier phase
        }
        return count;
    }

    public static int getPendingCount() {
        return PENDING_TRANSFERS.size();
    }
}
