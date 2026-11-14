package com.lynx.multicore.agent;

import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.ThreadFactory;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.logging.Level;
import java.util.logging.Logger;

/**
 * Parallel dimension dispatcher for Overworld, Nether, The End, and custom dimensions.
 * Dispatches dimension level ticks concurrently across dedicated threads,
 * synchronized with a barrier prior to client network packet flushes.
 */
public class DimensionDispatcher {
    private static final Logger LOGGER = Logger.getLogger("LMCE-DimensionDispatcher");
    private static final AtomicInteger THREAD_COUNTER = new AtomicInteger(0);
    private static volatile ExecutorService dimensionExecutor;
    private static volatile boolean active = false;

    public static synchronized void initialize(int cores, String mode) {
        int dimThreads = Math.max(2, cores);
        ThreadFactory factory = new ThreadFactory() {
            @Override
            public Thread newThread(Runnable r) {
                int id = THREAD_COUNTER.getAndIncrement();
                Thread t = new Thread(r, "Multicore-Dim-" + id);
                t.setDaemon(true);
                t.setPriority(Thread.NORM_PRIORITY + 1); // elevated priority to avoid dimension starvation
                return t;
            }
        };

        dimensionExecutor = Executors.newFixedThreadPool(dimThreads, factory);
        active = true;
        LOGGER.info("[LMCE] Initialized DimensionDispatcher with " + dimThreads + " worker threads (mode=" + mode + ").");
    }

    /**
     * Executes dimension level ticking in parallel with barrier synchronization.
     * Guaranteed to complete before connection packet flush.
     */
    public static void tickDimensionsParallel(Iterable<?> levels, Object timeSupplier) {
        if (!active || dimensionExecutor == null || levels == null) {
            fallbackSequentialTick(levels, timeSupplier);
            return;
        }

        WorldSaveBarrier.acquireTick();
        try {
            List<CompletableFuture<Void>> futures = new ArrayList<CompletableFuture<Void>>();

            for (final Object level : levels) {
                if (level == null) continue;

                futures.add(CompletableFuture.runAsync(new Runnable() {
                    @Override
                    public void run() {
                        try {
                            invokeLevelTick(level, timeSupplier);
                        } catch (Throwable t) {
                            LOGGER.log(Level.SEVERE, "[LMCE] Exception during parallel tick of " + level, t);
                        }
                    }
                }, dimensionExecutor));
            }

            // Barrier Synchronization: Await completion of all dimensions before packet broadcast
            CompletableFuture.allOf(futures.toArray(new CompletableFuture[0])).join();

            // Process deferred inter-dimension entity transfers
            DimensionTransferQueue.flushPendingTransfers();

        } finally {
            WorldSaveBarrier.releaseTick();
        }
    }

    private static void invokeLevelTick(Object level, Object timeSupplier) {
        try {
            // Attempt to invoke tick(BooleanSupplier) or tick() on level
            Method[] methods = level.getClass().getMethods();
            for (Method m : methods) {
                if (m.getName().equals("tick") || m.getName().equals("func_72835_b")) {
                    Class<?>[] pts = m.getParameterTypes();
                    if (pts.length == 1 && timeSupplier != null && pts[0].isInstance(timeSupplier)) {
                        m.invoke(level, timeSupplier);
                        return;
                    } else if (pts.length == 0) {
                        m.invoke(level);
                        return;
                    }
                }
            }
        } catch (Throwable t) {
            LOGGER.log(Level.FINE, "[LMCE] Reflection tick invoke failed on " + level, t);
        }
    }

    private static void fallbackSequentialTick(Iterable<?> levels, Object timeSupplier) {
        if (levels == null) return;
        for (Object level : levels) {
            if (level != null) {
                invokeLevelTick(level, timeSupplier);
            }
        }
    }

    public static boolean isActive() {
        return active;
    }
}
