package com.lynx.multicore.agent;

import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.ForkJoinPool;
import java.util.concurrent.ThreadFactory;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.logging.Logger;

/**
 * Scales JVM worker pools and Minecraft background chunk generation workers.
 * Uncaps Vanilla's hardcoded 7-thread limit on Util.backgroundExecutor() and
 * sizes ForkJoinPool.commonPool and Netty event loops to all allocated cores.
 * Threads are named Multicore-Worker-N for real-time telemetry sampling.
 */
public class WorkerPoolScaler {
    private static final Logger LOGGER = Logger.getLogger("LMCE-WorkerScaler");
    private static final AtomicInteger THREAD_COUNTER = new AtomicInteger(0);
    private static volatile ExecutorService workerExecutor;
    private static volatile int activeWorkerCount = 0;

    public static synchronized void initialize(int cores) {
        int targetThreads = Math.max(2, cores);
        activeWorkerCount = targetThreads;

        // 1. Scale ForkJoinPool.commonPool parallelism if not explicitly set
        if (System.getProperty("java.util.concurrent.ForkJoinPool.common.parallelism") == null) {
            System.setProperty("java.util.concurrent.ForkJoinPool.common.parallelism", String.valueOf(targetThreads));
        }

        // 2. Scale Netty event loop threads
        if (System.getProperty("io.netty.eventLoopThreads") == null) {
            int nettyThreads = Math.min(16, Math.max(2, targetThreads));
            System.setProperty("io.netty.eventLoopThreads", String.valueOf(nettyThreads));
        }

        // 3. Initialize uncapped worker pool with telemetry-friendly names
        ThreadFactory threadFactory = new ThreadFactory() {
            @Override
            public Thread newThread(Runnable r) {
                int id = THREAD_COUNTER.getAndIncrement();
                Thread t = new Thread(r, "Multicore-Worker-" + id);
                t.setDaemon(true);
                t.setPriority(Thread.NORM_PRIORITY);
                return t;
            }
        };

        workerExecutor = Executors.newFixedThreadPool(targetThreads, threadFactory);
        LOGGER.info("[LMCE] Scaled background worker pool to " + targetThreads + " threads (Multicore-Worker-N).");
    }

    public static ExecutorService getWorkerExecutor() {
        return workerExecutor;
    }

    public static int getActiveWorkerCount() {
        return activeWorkerCount;
    }
}
