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
        EasyCrValidation.validateSymbol("CheckConfirmProposalTime");
        expectFailure(() -> EasyCrValidation.validateSymbol("bad-symbol"));

        Path root = Files.createTempDirectory("easy-cr-validation").toRealPath();
        Path file = root.resolve("sample.go");
        Files.writeString(file, "package sample\n// 中文\n");
        require(EasyCrValidation.resolveGoFile(root, "sample.go").equals(file), "repo file");
        expectFailure(() -> EasyCrValidation.resolveGoFile(root, "../outside.go"));
        require(EasyCrValidation.editorColumn(file, 2, 4) == 3, "utf8 to utf16");
        require(EasyCrValidation.utf8ByteColumn("// 中文", 3) == 4, "utf16 to utf8");
        expectFailure(() -> EasyCrValidation.editorColumn(file, 2, 5));
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
