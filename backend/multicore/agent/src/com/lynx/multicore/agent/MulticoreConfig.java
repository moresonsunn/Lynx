package com.lynx.multicore.agent;

import java.util.HashMap;
import java.util.Map;

/**
 * Configuration parser for the Lynx Multi-Core Engine Universal Java Agent.
 */
public class MulticoreConfig {
    private final int cores;
    private final String mode;
    private final boolean asyncSave;
    private final boolean bytecodeTransformEnabled;

    public MulticoreConfig(int cores, String mode, boolean asyncSave, boolean bytecodeTransformEnabled) {
        this.cores = Math.max(2, cores);
        this.mode = (mode != null && !mode.trim().isEmpty()) ? mode.trim().toLowerCase() : "auto";
        this.asyncSave = asyncSave;
        this.bytecodeTransformEnabled = bytecodeTransformEnabled;
    }

    public static MulticoreConfig parse(String agentArgs) {
        Map<String, String> params = new HashMap<String, String>();
        if (agentArgs != null && !agentArgs.trim().isEmpty()) {
            String[] tokens = agentArgs.split(",");
            for (String token : tokens) {
                String[] kv = token.split("=", 2);
                if (kv.length == 2) {
                    params.put(kv[0].trim().toLowerCase(), kv[1].trim());
                }
            }
        }

        // 1. Resolve Cores
        int detectedCores = Runtime.getRuntime().availableProcessors();
        int cores = detectedCores;

        String threadsParam = params.get("threads");
        if (threadsParam == null) {
            threadsParam = params.get("cores");
        }
        if (threadsParam == null) {
            threadsParam = System.getProperty("multicore.threads");
        }
        if (threadsParam == null) {
            threadsParam = System.getProperty("multicore.cores");
        }

        if (threadsParam != null) {
            try {
                int parsed = Integer.parseInt(threadsParam.trim());
                if (parsed > 0) {
                    cores = parsed;
                }
            } catch (NumberFormatException ignored) {}
        }

        // 2. Resolve Mode
        String mode = params.get("mode");
        if (mode == null) {
            mode = System.getProperty("multicore.mode", "auto");
        }

        // 3. Resolve async save
        boolean asyncSave = true;
        String asyncParam = params.get("asyncsave");
        if (asyncParam != null) {
            asyncSave = !"false".equalsIgnoreCase(asyncParam.trim());
        }

        // 4. Transform flag
        boolean transform = true;
        String transformParam = params.get("transform");
        if (transformParam != null) {
            transform = !"false".equalsIgnoreCase(transformParam.trim());
        }

        return new MulticoreConfig(cores, mode, asyncSave, transform);
    }

    public int getCores() {
        return cores;
    }

    public String getMode() {
        return mode;
    }

    public boolean isAsyncSave() {
        return asyncSave;
    }

    public boolean isBytecodeTransformEnabled() {
        return bytecodeTransformEnabled;
    }
}
