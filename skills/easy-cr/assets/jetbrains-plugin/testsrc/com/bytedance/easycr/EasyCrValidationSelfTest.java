package com.bytedance.easycr;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;

public final class EasyCrValidationSelfTest {
    public static void main(String[] args) throws Exception {
        require(EasyCrValidation.isAllowedOrigin(null), "missing origin");
        require(EasyCrValidation.isAllowedOrigin("null"), "file origin");
        require(EasyCrValidation.isAllowedOrigin("http://127.0.0.1:61234"), "loopback origin");
        require(!EasyCrValidation.isAllowedOrigin("https://evil.example"), "external origin");
        require(EasyCrValidation.tokenMatches("secret".getBytes(StandardCharsets.UTF_8), "secret"), "token");
        require(!EasyCrValidation.tokenMatches("secret".getBytes(StandardCharsets.UTF_8), "other"), "bad token");

        EasyCrValidation.validateReviewInputs("HEAD^", 1, 1, 10);
        expectFailure(() -> EasyCrValidation.validateReviewInputs("bad revision!", 1, 1, 10));
        expectFailure(() -> EasyCrValidation.validateReviewInputs("HEAD^", 0, 1, 10));

        Path root = Files.createTempDirectory("easy-cr-validation").toRealPath();
        Path goFile = root.resolve("sample.go");
        Files.writeString(goFile, "package sample\n// 中文\n");
        Path javaFile = root.resolve("Sample.java");
        Files.writeString(javaFile, "class Sample {}\n");
        require(EasyCrValidation.resolveSourceFile(root, "sample.go").equals(goFile), "go repo file");
        require(EasyCrValidation.resolveSourceFile(root, "Sample.java").equals(javaFile), "java repo file");
        expectFailure(() -> EasyCrValidation.resolveSourceFile(root, "../outside.go"));
        expectFailure(() -> EasyCrValidation.resolveSourceFile(root, "missing.go"));
        require(EasyCrValidation.editorColumn(goFile, 2, 4) == 3, "utf8 to utf16");
        require(EasyCrValidation.utf8ByteColumn("// 中文", 3) == 4, "utf16 to utf8");
        expectFailure(() -> EasyCrValidation.editorColumn(goFile, 2, 5));
    }

    private static void require(boolean value, String message) {
        if (!value) {
            throw new AssertionError(message);
        }
    }

    private static void expectFailure(ThrowingRunnable runnable) throws Exception {
        try {
            runnable.run();
        } catch (IllegalArgumentException expected) {
            return;
        }
        throw new AssertionError("expected IllegalArgumentException");
    }

    @FunctionalInterface
    private interface ThrowingRunnable {
        void run() throws Exception;
    }
}
