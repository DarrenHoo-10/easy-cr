package com.bytedance.easycr;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.Set;
import java.util.regex.Pattern;

final class EasyCrValidation {
    private static final Pattern REVISION = Pattern.compile("[A-Za-z0-9_./^~{}@:+-]{1,200}");
    private static final Set<String> LOOPBACK_HOSTS = Set.of("127.0.0.1", "localhost");

    private EasyCrValidation() {
    }

    static boolean isAllowedOrigin(String origin) {
        if (origin == null || "null".equals(origin)) {
            return true;
        }
        try {
            java.net.URI uri = java.net.URI.create(origin);
            return "http".equals(uri.getScheme()) && LOOPBACK_HOSTS.contains(uri.getHost());
        } catch (IllegalArgumentException error) {
            return false;
        }
    }

    static boolean tokenMatches(byte[] expected, String supplied) {
        return MessageDigest.isEqual(expected, supplied.getBytes(StandardCharsets.UTF_8));
    }

    static void validateReviewInputs(String base, int line, int column, int context) {
        if (!REVISION.matcher(base).matches()) {
            throw new IllegalArgumentException("base revision 非法");
        }
        if (line < 1 || column < 1) {
            throw new IllegalArgumentException("行列必须为正整数");
        }
        if (context < 0 || context > 100) {
            throw new IllegalArgumentException("context 必须在 0 到 100 之间");
        }
    }

    static Path resolveSourceFile(Path root, String relativePath) throws IOException {
        if (relativePath.isBlank() || relativePath.indexOf('\0') >= 0) {
            throw new IllegalArgumentException("文件路径非法");
        }
        Path normalized = root.resolve(relativePath).normalize();
        if (!normalized.startsWith(root)) {
            throw new IllegalArgumentException("目标必须是仓库内已有文件");
        }
        final Path target;
        try {
            target = normalized.toRealPath();
        } catch (IOException error) {
            throw new IllegalArgumentException("目标必须是仓库内已有文件", error);
        }
        if (!target.startsWith(root) || !Files.isRegularFile(target)) {
            throw new IllegalArgumentException("目标必须是仓库内已有文件");
        }
        return target;
    }

    static int editorColumn(Path target, int oneBasedLine, int utf8ByteColumn) throws IOException {
        java.util.List<String> lines = Files.readAllLines(target, StandardCharsets.UTF_8);
        if (oneBasedLine > lines.size()) {
            throw new IllegalArgumentException("行号超出文件范围");
        }
        String line = lines.get(oneBasedLine - 1);
        int requestedBytes = utf8ByteColumn - 1;
        int consumedBytes = 0;
        int utf16Column = 0;
        while (utf16Column < line.length() && consumedBytes < requestedBytes) {
            int codePoint = line.codePointAt(utf16Column);
            int codeUnits = Character.charCount(codePoint);
            int encodedBytes = new String(Character.toChars(codePoint))
                    .getBytes(StandardCharsets.UTF_8).length;
            if (consumedBytes + encodedBytes > requestedBytes) {
                throw new IllegalArgumentException("列号不在 UTF-8 字符边界");
            }
            consumedBytes += encodedBytes;
            utf16Column += codeUnits;
        }
        if (consumedBytes != requestedBytes || utf16Column > line.length()) {
            throw new IllegalArgumentException("列号超出行范围");
        }
        return utf16Column;
    }

    static int utf8ByteColumn(String line, int utf16Column) {
        if (utf16Column < 0 || utf16Column > line.length()) {
            throw new IllegalArgumentException("UTF-16 列号超出行范围");
        }
        return line.substring(0, utf16Column).getBytes(StandardCharsets.UTF_8).length + 1;
    }
}
