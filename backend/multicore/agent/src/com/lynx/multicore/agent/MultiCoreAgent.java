package com.lynx.multicore.agent;

import java.lang.instrument.Instrumentation;
import java.util.logging.Logger;

/**
 * Universal Multi-Core Java Agent entrypoint for Minecraft-Controller LMCE.
 * Attaches to any Minecraft JVM (Vanilla, Paper, Forge, NeoForge across Java 8 - 25+)
 * via -javaagent to orchestrate parallel dimension ticking, background worker scaling,
 * and atomic world serialization guards.
 */
public class MultiCoreAgent {
    private static final Logger LOGGER = Logger.getLogger("LMCE-Agent");
    private static volatile boolean initialized = false;

    public static void premain(String agentArgs, Instrumentation inst) {
        init(agentArgs, inst);
    }

    public static void agentmain(String agentArgs, Instrumentation inst) {
        init(agentArgs, inst);
    }

    public static synchronized void init(String agentArgs, Instrumentation inst) {
        if (initialized) {
            return;
        }
        initialized = true;

        // 1. Output Startup Telemetry Banner
        printBanner();

        // 2. Parse Configuration Parameters
        MulticoreConfig config = MulticoreConfig.parse(agentArgs);
        int cores = config.getCores();
        String mode = config.getMode();

        LOGGER.info("[LMCE] Active Configuration: cores=" + cores + ", mode=" + mode + ", asyncSave=" + config.isAsyncSave());

        // 3. Scale Background Worker Pools & Netty Event Loops
        WorkerPoolScaler.initialize(cores);

        // 4. Initialize Parallel Dimension Dispatcher
        DimensionDispatcher.initialize(cores, mode);

        // 5. Register Graceful Shutdown World Flush Guard
        if (config.isAsyncSave()) {
            WorldSaveBarrier.registerShutdownHook();
        }

        // 6. Record System Properties for Controller Telemetry
        System.setProperty("minecraft.multicore.enabled", "true");
        System.setProperty("minecraft.multicore.cores", String.valueOf(cores));
        System.setProperty("minecraft.multicore.mode", mode);
        System.setProperty("minecraft.multicore.agent.loaded", "true");

        LOGGER.info("[LMCE] Universal Multi-Core Agent successfully initialized and armed.");
    }

    private static void printBanner() {
        LOGGER.info("================================================================================");
        LOGGER.info("       Lynx Multi-Core Engine (LMCE) - Universal Java Agent                     ");
        LOGGER.info("       Parallel Dimension Dispatching & Background Worker Acceleration          ");
        LOGGER.info("       Bytecode Target: Java 8+ Universal Compatibility                         ");
        LOGGER.info("================================================================================");
    }

    public static boolean isInitialized() {
        return initialized;
    }
}
