package com.lynx.multicore.tests;

import com.lynx.multicore.agent.DimensionDispatcher;
import com.lynx.multicore.agent.DimensionTransferQueue;
import com.lynx.multicore.agent.MultiCoreAgent;
import com.lynx.multicore.agent.WorkerPoolScaler;
import com.lynx.multicore.agent.WorldSaveBarrier;

import java.lang.management.ManagementFactory;
import java.lang.management.ThreadInfo;
import java.lang.management.ThreadMXBean;
import java.util.ArrayList;
import java.util.List;
import java.util.Random;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;

/**
 * Empirical concurrency stress harness for LMCE Universal Java Agent.
 * Stress tests:
 * 1. Parallel dimension ticking across worker threads.
 * 2. Atomic world save lock acquisition under high contention.
 * 3. Mutual exclusion between dimension ticks and world save flush.
 * 4. Inter-dimension entity transfer queue concurrency.
 * 5. Deadlock detection via ThreadMXBean.
 */
public class AgentStressHarness {

    private static final AtomicInteger ACTIVE_TICKS = new AtomicInteger(0);
    private static final AtomicInteger ACTIVE_SAVERS = new AtomicInteger(0);
    private static final AtomicLong TOTAL_TICKS = new AtomicLong(0);
    private static final AtomicLong TOTAL_SAVES = new AtomicLong(0);
    private static final AtomicLong TOTAL_TRANSFERS = new AtomicLong(0);
    private static final AtomicInteger CONCURRENCY_VIOLATIONS = new AtomicInteger(0);
    private static final List<String> VIOLATION_LOGS = new CopyOnWriteArrayList<String>();

    public static class MockLevel {
        private final String name;
        private final AtomicInteger tickCount = new AtomicInteger(0);

        public MockLevel(String name) {
            this.name = name;
        }

        // Method signature recognized by DimensionDispatcher.invokeLevelTick
        public void tick() {
            int savers = ACTIVE_SAVERS.get();
            if (savers > 0) {
                String err = "MUTUAL EXCLUSION VIOLATION: Level [" + name + "] is ticking while " + savers + " save threads hold write lock!";
                VIOLATION_LOGS.add(err);
                CONCURRENCY_VIOLATIONS.incrementAndGet();
            }

            ACTIVE_TICKS.incrementAndGet();
            try {
                tickCount.incrementAndGet();
                TOTAL_TICKS.incrementAndGet();
                // Simulate realistic dimension tick computation & memory access
                int sum = 0;
                for (int i = 0; i < 500; i++) {
                    sum += (i * 31);
                }
                if (sum == -1) System.out.print("");

                // Intermittent brief jitter
                if (tickCount.get() % 50 == 0) {
                    try {
                        Thread.sleep(1);
                    } catch (InterruptedException ignored) {}
                }

                // Check again before leaving
                savers = ACTIVE_SAVERS.get();
                if (savers > 0) {
                    String err = "MUTUAL EXCLUSION VIOLATION: Level [" + name + "] finished tick while " + savers + " save threads hold write lock!";
                    VIOLATION_LOGS.add(err);
                    CONCURRENCY_VIOLATIONS.incrementAndGet();
                }
            } finally {
                ACTIVE_TICKS.decrementAndGet();
            }
        }

        public String getName() {
            return name;
        }

        public int getTickCount() {
            return tickCount.get();
        }
    }

    public static void main(String[] args) throws Exception {
        System.out.println("================================================================================");
        System.out.println("[AgentStressHarness] Starting LMCE Concurrency Stress Test Harness...");
        System.out.println("================================================================================");

        int cores = 8;
        if (args.length > 0) {
            try {
                cores = Integer.parseInt(args[0]);
            } catch (NumberFormatException ignored) {}
        }

        // 1. Initialize agent subsystems
        WorkerPoolScaler.initialize(cores);
        DimensionDispatcher.initialize(cores, "stress_test");

        System.out.println("[AgentStressHarness] Initialized with " + cores + " worker threads.");

        // 2. Setup mock dimensions (Overworld, Nether, The End, and 2 Custom Dimensions)
        final List<MockLevel> levels = new ArrayList<MockLevel>();
        levels.add(new MockLevel("minecraft:overworld"));
        levels.add(new MockLevel("minecraft:the_nether"));
        levels.add(new MockLevel("minecraft:the_end"));
        levels.add(new MockLevel("custom:mining_dimension"));
        levels.add(new MockLevel("custom:deep_dark"));

        final AtomicBoolean running = new AtomicBoolean(true);
        final ThreadMXBean threadBean = ManagementFactory.getThreadMXBean();

        // 3. Launch Watchdog for Deadlock Detection
        Thread watchdog = new Thread(new Runnable() {
            @Override
            public void run() {
                while (running.get()) {
                    long[] deadlocks = threadBean.findDeadlockedThreads();
                    if (deadlocks != null && deadlocks.length > 0) {
                        System.err.println("[AgentStressHarness] DEADLOCK DETECTED! Thread IDs: " + deadlocks.length);
                        ThreadInfo[] infos = threadBean.getThreadInfo(deadlocks, true, true);
                        for (ThreadInfo info : infos) {
                            System.err.println(info);
                        }
                        CONCURRENCY_VIOLATIONS.incrementAndGet();
                        System.exit(2);
                    }
                    try {
                        Thread.sleep(50);
                    } catch (InterruptedException e) {
                        break;
                    }
                }
            }
        }, "Watchdog-DeadlockDetector");
        watchdog.setDaemon(true);
        watchdog.start();

        int tickThreadsCount = 6;
        int saveThreadsCount = 4;
        int transferThreadsCount = 4;
        final int ticksPerThread = 250;
        final int savesPerThread = 100;
        final int transfersPerThread = 1000;

        ExecutorService testExecutor = Executors.newFixedThreadPool(
                tickThreadsCount + saveThreadsCount + transferThreadsCount
        );

        long startTime = System.currentTimeMillis();
        List<Future<?>> futures = new ArrayList<Future<?>>();

        // 4. Submit Tick Threads
        for (int t = 0; t < tickThreadsCount; t++) {
            final int threadId = t;
            futures.add(testExecutor.submit(new Runnable() {
                @Override
                public void run() {
                    for (int i = 0; i < ticksPerThread; i++) {
                        DimensionDispatcher.tickDimensionsParallel(levels, null);
                        if (i % 20 == 0) {
                            Thread.yield();
                        }
                    }
                }
            }));
        }

        // 5. Submit World Save Contention Threads
        for (int s = 0; s < saveThreadsCount; s++) {
            final int saverId = s;
            futures.add(testExecutor.submit(new Runnable() {
                @Override
                public void run() {
                    Random rnd = new Random(saverId);
                    for (int i = 0; i < savesPerThread; i++) {
                        // Attempt to acquire atomic world save lock
                        WorldSaveBarrier.beginAtomicWorldSave();
                        try {
                            // CRITICAL INVARIANT: While write lock is held, ACTIVE_TICKS MUST BE 0!
                            int currentTicks = ACTIVE_TICKS.get();
                            if (currentTicks > 0) {
                                String err = "MUTUAL EXCLUSION VIOLATION: World save acquired write lock while " + currentTicks + " dimension ticks are active!";
                                VIOLATION_LOGS.add(err);
                                CONCURRENCY_VIOLATIONS.incrementAndGet();
                            }

                            int prevSavers = ACTIVE_SAVERS.getAndIncrement();
                            if (prevSavers > 0) {
                                // Since ReentrantReadWriteLock is exclusive on write lock, two threads cannot both hold write lock!
                                String err = "WRITE LOCK VIOLATION: Multiple save threads hold write lock concurrently! (" + (prevSavers + 1) + ")";
                                VIOLATION_LOGS.add(err);
                                CONCURRENCY_VIOLATIONS.incrementAndGet();
                            }

                            TOTAL_SAVES.incrementAndGet();

                            // Simulate flush latency (e.g. disk write operations)
                            try {
                                Thread.sleep(1 + rnd.nextInt(3));
                            } catch (InterruptedException ignored) {}

                            // Invariant check again before unlock
                            currentTicks = ACTIVE_TICKS.get();
                            if (currentTicks > 0) {
                                String err = "MUTUAL EXCLUSION VIOLATION: Dimension ticks running during world save flush! (" + currentTicks + ")";
                                VIOLATION_LOGS.add(err);
                                CONCURRENCY_VIOLATIONS.incrementAndGet();
                            }

                            ACTIVE_SAVERS.decrementAndGet();
                        } finally {
                            WorldSaveBarrier.endAtomicWorldSave();
                        }

                        // Jitter before next save request
                        try {
                            Thread.sleep(rnd.nextInt(5));
                        } catch (InterruptedException ignored) {}
                    }
                }
            }));
        }

        // 6. Submit Inter-Dimension Transfer Threads
        for (int tr = 0; tr < transferThreadsCount; tr++) {
            final int trId = tr;
            futures.add(testExecutor.submit(new Runnable() {
                @Override
                public void run() {
                    for (int i = 0; i < transfersPerThread; i++) {
                        DimensionTransferQueue.enqueueTransfer(
                                "Entity-" + trId + "-" + i,
                                levels.get(0),
                                levels.get(1),
                                100.0 + i, 64.0, 200.0 + i
                        );
                        TOTAL_TRANSFERS.incrementAndGet();
                        if (i % 100 == 0) {
                            int flushed = DimensionTransferQueue.flushPendingTransfers();
                        }
                    }
                }
            }));
        }

        // 7. Await all tasks completion
        for (Future<?> f : futures) {
            f.get(60, TimeUnit.SECONDS); // 60s timeout guard against hung tasks
        }

        running.set(false);
        testExecutor.shutdown();
        boolean finished = testExecutor.awaitTermination(10, TimeUnit.SECONDS);

        // Final flush of any remaining transfers
        DimensionTransferQueue.flushPendingTransfers();

        long elapsed = System.currentTimeMillis() - startTime;

        System.out.println("================================================================================");
        System.out.println("[AgentStressHarness] Stress Test Completed in " + elapsed + " ms.");
        System.out.println("  - Total Dimension Ticks: " + TOTAL_TICKS.get());
        System.out.println("  - Total World Saves:    " + TOTAL_SAVES.get());
        System.out.println("  - Total Transfers:      " + TOTAL_TRANSFERS.get());
        System.out.println("  - Concurrency Violations: " + CONCURRENCY_VIOLATIONS.get());
        System.out.println("  - Executor Terminated:   " + finished);
        System.out.println("================================================================================");

        if (!VIOLATION_LOGS.isEmpty()) {
            System.err.println("[AgentStressHarness] Concurrency Violations Recorded:");
            for (String log : VIOLATION_LOGS) {
                System.err.println("  [FAIL] " + log);
            }
        }

        if (CONCURRENCY_VIOLATIONS.get() > 0) {
            System.err.println("[AgentStressHarness] STRESS TEST FAILED with " + CONCURRENCY_VIOLATIONS.get() + " violations.");
            System.exit(1);
        } else {
            System.out.println("[AgentStressHarness] SUCCESS: Zero deadlocks, zero race conditions, full mutual exclusion verified.");
            System.exit(0);
        }
    }
}
