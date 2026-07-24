package com.bytedance.easycr;

import com.goide.psi.GoReferencesSearch;
import com.google.gson.Gson;
import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import com.google.gson.JsonParseException;
import com.intellij.openapi.Disposable;
import com.intellij.openapi.application.ApplicationManager;
import com.intellij.openapi.diagnostic.Logger;
import com.intellij.openapi.editor.Document;
import com.intellij.openapi.editor.Editor;
import com.intellij.openapi.fileEditor.FileEditorManager;
import com.intellij.openapi.fileEditor.OpenFileDescriptor;
import com.intellij.openapi.project.Project;
import com.intellij.openapi.project.ProjectManager;
import com.intellij.openapi.util.Computable;
import com.intellij.openapi.util.TextRange;
import com.intellij.openapi.vfs.LocalFileSystem;
import com.intellij.openapi.vfs.VirtualFile;
import com.intellij.openapi.wm.IdeFrame;
import com.intellij.openapi.wm.IdeFocusManager;
import com.intellij.openapi.wm.WindowManager;
import com.intellij.psi.PsiDocumentManager;
import com.intellij.psi.PsiElement;
import com.intellij.psi.PsiFile;
import com.intellij.psi.PsiNamedElement;
import com.intellij.psi.PsiReference;
import com.intellij.psi.search.GlobalSearchScope;
import com.intellij.ui.AppIcon;
import com.sun.net.httpserver.Headers;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;

import java.io.IOException;
import java.io.InputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

public final class EasyCrHttpService implements Disposable {
    private static final Logger LOG = Logger.getInstance(EasyCrHttpService.class);
    private static final Gson GSON = new Gson();
    private static final int MAX_BODY_BYTES = 32 * 1024;
    private static final int MAX_REFERENCES = 500;
    private static final Path TOKEN_PATH = Path.of(
            System.getProperty("user.home"),
            ".config",
            "easy-cr",
            "goland-token"
    );

    private final ExecutorService executor = Executors.newFixedThreadPool(2, runnable -> {
        Thread thread = new Thread(runnable, "easy-cr-http");
        thread.setDaemon(true);
        return thread;
    });
    private HttpServer server;
    private byte[] token;

    public EasyCrHttpService() {
        try {
            token = readToken();
            server = HttpServer.create(new InetSocketAddress("127.0.0.1", 64343), 0);
            server.createContext("/api/references", exchange -> handle(exchange, true));
            server.createContext("/api/open", exchange -> handle(exchange, false));
            server.createContext("/api/health", this::handleHealth);
            server.setExecutor(executor);
            server.start();
            LOG.info("Easy CR endpoint started at http://127.0.0.1:64343");
        } catch (Exception error) {
            LOG.error("Unable to start Easy CR endpoint", error);
        }
    }

    private void handleHealth(HttpExchange exchange) throws IOException {
        String origin = exchange.getRequestHeaders().getFirst("Origin");
        if (!EasyCrValidation.isAllowedOrigin(origin)) {
            respond(exchange, 403, error("不允许的请求来源"), null);
            return;
        }
        addCors(exchange.getResponseHeaders(), origin);
        if ("OPTIONS".equals(exchange.getRequestMethod())) {
            exchange.sendResponseHeaders(204, -1);
            exchange.close();
            return;
        }
        if (!"POST".equals(exchange.getRequestMethod())) {
            respond(exchange, 405, error("只支持 POST"), origin);
            return;
        }
        String contentType = exchange.getRequestHeaders().getFirst("Content-Type");
        if (contentType == null || !contentType.toLowerCase().startsWith("application/json")) {
            respond(exchange, 400, error("Content-Type 必须为 application/json"), origin);
            return;
        }
        String supplied = exchange.getRequestHeaders().getFirst("X-Easy-CR-Token");
        if (supplied == null || !EasyCrValidation.tokenMatches(token, supplied)) {
            respond(exchange, 401, error("无效 token"), origin);
            return;
        }
        JsonObject result = new JsonObject();
        result.addProperty("ready", true);
        result.addProperty("plugin", "easy-cr");
        respond(exchange, 200, result, origin);
    }

    private static byte[] readToken() throws IOException {
        String value = Files.readString(TOKEN_PATH, StandardCharsets.UTF_8).trim();
        if (!value.matches("[A-Za-z0-9_-]{32,}")) {
            throw new IOException("Invalid Easy CR token; run configure.py set goland");
        }
        return value.getBytes(StandardCharsets.UTF_8);
    }

    private void handle(HttpExchange exchange, boolean queryReferences) throws IOException {
        String origin = exchange.getRequestHeaders().getFirst("Origin");
        if (!EasyCrValidation.isAllowedOrigin(origin)) {
            respond(exchange, 403, error("不允许的请求来源"), null);
            return;
        }
        addCors(exchange.getResponseHeaders(), origin);
        if ("OPTIONS".equals(exchange.getRequestMethod())) {
            exchange.sendResponseHeaders(204, -1);
            exchange.close();
            return;
        }
        if (!"POST".equals(exchange.getRequestMethod())) {
            respond(exchange, 405, error("只支持 POST"), origin);
            return;
        }
        String contentType = exchange.getRequestHeaders().getFirst("Content-Type");
        if (contentType == null || !contentType.toLowerCase().startsWith("application/json")) {
            respond(exchange, 400, error("Content-Type 必须为 application/json"), origin);
            return;
        }
        try {
            JsonObject request = GSON.fromJson(
                    new String(readLimited(exchange.getRequestBody()), StandardCharsets.UTF_8),
                    JsonObject.class
            );
            if (request == null) {
                throw new IllegalArgumentException("请求体不能为空");
            }
            requireToken(request);
            RequestContext context = parseContext(request);
            if (queryReferences) {
                String symbol = stringField(request, "symbol");
                EasyCrValidation.validateSymbol(symbol);
                List<ReferenceResult> references = queryReferences(context, symbol);
                boolean opened = false;
                if (references.isEmpty()) {
                    openAt(context.project(), context.target(), context.line(), context.editorColumn());
                    opened = true;
                } else if (references.size() == 1) {
                    openReferenceResult(context, references.get(0));
                    opened = true;
                }
                JsonObject result = new JsonObject();
                result.addProperty("symbol", symbol);
                result.addProperty("opened", opened);
                JsonArray values = new JsonArray();
                references.forEach(reference -> values.add(reference.toJson()));
                result.add("references", values);
                respond(exchange, 200, result, origin);
            } else {
                openAt(context.project(), context.target(), context.line(), context.editorColumn());
                JsonObject result = new JsonObject();
                result.addProperty("opened", true);
                respond(exchange, 200, result, origin);
            }
        } catch (IllegalArgumentException | JsonParseException error) {
            respond(exchange, 400, error(error.getMessage()), origin);
        } catch (ReviewConflict error) {
            respond(exchange, 409, error(error.getMessage()), origin);
        } catch (Exception error) {
            LOG.warn("Easy CR request failed", error);
            respond(exchange, 500, error("GoLand 处理失败：" + safeMessage(error)), origin);
        }
    }

    private RequestContext parseContext(JsonObject request) throws Exception {
        String projectPath = stringField(request, "projectPath");
        String filePath = stringField(request, "filePath");
        String reviewType = stringField(request, "reviewType");
        String fingerprint = stringField(request, "fingerprint");
        String base = stringField(request, "base");
        int line = intField(request, "line");
        int column = intField(request, "column");
        int context = intField(request, "context");
        EasyCrValidation.validateReviewInputs(base, line, column, context);

        Project project = findOpenProject(projectPath);
        Path root = Path.of(project.getBasePath()).toRealPath();
        validateReview(root, reviewType, fingerprint, base, context);
        Path target = EasyCrValidation.resolveGoFile(root, filePath);
        int editorColumn = EasyCrValidation.editorColumn(target, line, column);
        return new RequestContext(project, root, target, line, editorColumn);
    }

    private List<ReferenceResult> queryReferences(RequestContext context, String symbol) {
        return ApplicationManager.getApplication().runReadAction(
                (Computable<List<ReferenceResult>>) () -> findReferences(context, symbol)
        );
    }

    private static void openReferenceResult(
            RequestContext context,
            ReferenceResult reference
    ) throws IOException {
        Path target = EasyCrValidation.resolveGoFile(context.root(), reference.path());
        int editorColumn = EasyCrValidation.editorColumn(target, reference.line(), reference.column());
        openAt(context.project(), target, reference.line(), editorColumn);
    }

    private List<ReferenceResult> findReferences(RequestContext context, String symbol) {
        VirtualFile source = LocalFileSystem.getInstance()
                .refreshAndFindFileByNioFile(context.target());
        if (source == null) {
            throw new IllegalStateException("GoLand 无法解析文件：" + context.target());
        }
        PsiFile psiFile = com.intellij.psi.PsiManager.getInstance(context.project())
                .findFile(source);
        if (psiFile == null) {
            throw new IllegalStateException("GoLand 无法读取 PSI 文件");
        }
        Document document = PsiDocumentManager.getInstance(context.project())
                .getDocument(psiFile);
        if (document == null) {
            throw new IllegalStateException("GoLand 无法读取 PSI 文档");
        }
        int lineIndex = context.line() - 1;
        int offset = document.getLineStartOffset(lineIndex) + context.editorColumn();
        if (offset >= document.getTextLength()) {
            offset = Math.max(0, document.getTextLength() - 1);
        }
        PsiElement target = resolveTarget(psiFile, offset, symbol);
        Map<String, ReferenceResult> unique = new LinkedHashMap<>();
        for (PsiReference reference : GoReferencesSearch.search(
                target,
                GlobalSearchScope.projectScope(context.project())
        ).findAll()) {
            ReferenceResult result = toResult(context, reference);
            if (result == null) {
                continue;
            }
            unique.putIfAbsent(result.key(), result);
            if (unique.size() >= MAX_REFERENCES) {
                break;
            }
        }
        List<ReferenceResult> results = new ArrayList<>(unique.values());
        results.sort(Comparator
                .comparing(ReferenceResult::path)
                .thenComparingInt(ReferenceResult::line)
                .thenComparingInt(ReferenceResult::column));
        return results;
    }

    private static PsiElement resolveTarget(PsiFile file, int offset, String symbol) {
        PsiElement leaf = file.findElementAt(offset);
        if (leaf == null && offset > 0) {
            leaf = file.findElementAt(offset - 1);
        }
        if (leaf == null) {
            throw new IllegalArgumentException("无法识别点击位置的代码元素");
        }
        PsiNamedElement namedCandidate = null;
        for (PsiElement current = leaf; current != null && current != file; current = current.getParent()) {
            PsiReference reference = current.getReference();
            if (reference != null) {
                TextRange absolute = reference.getRangeInElement()
                        .shiftRight(current.getTextRange().getStartOffset());
                if (absolute.containsOffset(offset)) {
                    PsiElement resolved = reference.resolve();
                    if (resolved != null) {
                        return resolved;
                    }
                }
            }
            if (namedCandidate == null
                    && current instanceof PsiNamedElement named
                    && symbol.equals(named.getName())) {
                namedCandidate = named;
            }
        }
        if (namedCandidate != null) {
            return namedCandidate;
        }
        throw new IllegalArgumentException("无法解析符号：" + symbol);
    }

    private static ReferenceResult toResult(RequestContext context, PsiReference reference) {
        PsiElement element = reference.getElement();
        PsiFile file = element.getContainingFile();
        VirtualFile virtualFile = file == null ? null : file.getVirtualFile();
        Document document = file == null ? null
                : PsiDocumentManager.getInstance(context.project()).getDocument(file);
        if (virtualFile == null || document == null) {
            return null;
        }
        Path path;
        try {
            path = Path.of(virtualFile.getPath()).toRealPath();
        } catch (IOException error) {
            return null;
        }
        if (!path.startsWith(context.root()) || !path.toString().endsWith(".go")) {
            return null;
        }
        int offset = element.getTextRange().getStartOffset()
                + reference.getRangeInElement().getStartOffset();
        if (offset < 0 || offset > document.getTextLength()) {
            return null;
        }
        int lineIndex = document.getLineNumber(Math.min(offset, Math.max(0, document.getTextLength() - 1)));
        int lineStart = document.getLineStartOffset(lineIndex);
        int lineEnd = document.getLineEndOffset(lineIndex);
        String lineText = document.getText(new TextRange(lineStart, lineEnd));
        int utf16Column = Math.max(0, offset - lineStart);
        int byteColumn = EasyCrValidation.utf8ByteColumn(lineText, utf16Column);
        String preview = lineText.strip().replace('\t', ' ');
        if (preview.length() > 180) {
            preview = preview.substring(0, 177) + "...";
        }
        return new ReferenceResult(
                context.root().relativize(path).toString().replace('\\', '/'),
                lineIndex + 1,
                byteColumn,
                preview
        );
    }

    private static void openAt(Project project, Path target, int oneBasedLine, int zeroBasedColumn) {
        Runnable action = () -> {
            VirtualFile file = LocalFileSystem.getInstance().refreshAndFindFileByNioFile(target);
            if (file == null) {
                throw new IllegalStateException("GoLand 无法解析文件：" + target);
            }
            Editor editor = FileEditorManager.getInstance(project).openTextEditor(
                    new OpenFileDescriptor(project, file, oneBasedLine - 1, zeroBasedColumn),
                    true
            );
            if (editor == null) {
                throw new IllegalStateException("GoLand 无法打开文件：" + target);
            }
            IdeFrame frame = WindowManager.getInstance().getIdeFrame(project);
            if (frame != null) {
                AppIcon.getInstance().requestFocus(frame);
            } else {
                AppIcon.getInstance().requestFocus();
            }
            IdeFocusManager.getInstance(project).requestFocus(editor.getContentComponent(), true);
        };
        if (ApplicationManager.getApplication().isDispatchThread()) {
            action.run();
        } else {
            ApplicationManager.getApplication().invokeAndWait(action);
        }
    }

    private void requireToken(JsonObject request) {
        String supplied = stringField(request, "token");
        if (!EasyCrValidation.tokenMatches(token, supplied)) {
            throw new IllegalArgumentException("无效 token，请重新生成评审页");
        }
    }

    private static byte[] readLimited(InputStream input) throws IOException {
        byte[] body = input.readNBytes(MAX_BODY_BYTES + 1);
        if (body.length > MAX_BODY_BYTES) {
            throw new IllegalArgumentException("请求体过大");
        }
        return body;
    }

    private static String stringField(JsonObject request, String name) {
        if (!request.has(name) || !request.get(name).isJsonPrimitive()) {
            throw new IllegalArgumentException("缺少字段：" + name);
        }
        return request.get(name).getAsString();
    }

    private static int intField(JsonObject request, String name) {
        if (!request.has(name) || !request.get(name).isJsonPrimitive()) {
            throw new IllegalArgumentException("缺少字段：" + name);
        }
        try {
            return request.get(name).getAsInt();
        } catch (NumberFormatException error) {
            throw new IllegalArgumentException("字段必须为整数：" + name, error);
        }
    }

    private static void addCors(Headers headers, String origin) {
        if (origin != null) {
            headers.set("Access-Control-Allow-Origin", origin);
            headers.set("Vary", "Origin");
        }
        headers.set("Access-Control-Allow-Methods", "POST, OPTIONS");
        headers.set("Access-Control-Allow-Headers", "Content-Type, X-Easy-CR-Token");
        headers.set("Access-Control-Allow-Private-Network", "true");
        headers.set("Access-Control-Max-Age", "600");
    }

    private static Project findOpenProject(String projectPath) throws IOException {
        Path requested = Path.of(projectPath).toRealPath();
        return Arrays.stream(ProjectManager.getInstance().getOpenProjects())
                .filter(project -> matchesProject(project, requested))
                .findFirst()
                .orElseThrow(() -> new ReviewConflict("GoLand 未打开项目：" + requested));
    }

    private static boolean matchesProject(Project project, Path requested) {
        String basePath = project.getBasePath();
        if (project.isDisposed() || basePath == null) {
            return false;
        }
        try {
            return Path.of(basePath).toRealPath().equals(requested);
        } catch (IOException error) {
            return false;
        }
    }

    private static void validateReview(
            Path root,
            String reviewType,
            String fingerprint,
            String base,
            int context
    ) throws Exception {
        GitResult head = runGit(root, "rev-parse", "HEAD");
        requireGitSuccess(head, "读取 HEAD 失败");
        String headCommit = head.stdout().trim();
        String currentFingerprint;
        if ("revision".equals(reviewType)) {
            GitResult dirty = runGit(root, "diff", "--quiet", "HEAD", "--");
            if (dirty.exitCode() == 1) {
                throw new ReviewConflict("当前工作区存在 tracked 修改，请重新生成评审页");
            }
            requireGitSuccess(dirty, "检查工作区失败");
            currentFingerprint = headCommit;
        } else if ("worktree".equals(reviewType)) {
            GitResult diff = runGit(
                    root,
                    "diff",
                    "--no-ext-diff",
                    "--find-renames",
                    "--unified=" + context,
                    base,
                    "--"
            );
            requireGitSuccess(diff, "计算工作区 Diff 失败");
            currentFingerprint = sha256(headCommit + "\n" + diff.stdout());
        } else {
            throw new IllegalArgumentException("reviewType 非法");
        }
        if (!MessageDigest.isEqual(
                currentFingerprint.getBytes(StandardCharsets.UTF_8),
                fingerprint.getBytes(StandardCharsets.UTF_8)
        )) {
            throw new ReviewConflict("评审版本与当前工作区不一致，请重新生成评审页");
        }
    }

    private static GitResult runGit(Path root, String... arguments) throws Exception {
        List<String> command = new ArrayList<>();
        command.add("git");
        command.add("-C");
        command.add(root.toString());
        command.add("-c");
        command.add("core.quotePath=false");
        command.addAll(List.of(arguments));
        Process process = new ProcessBuilder(command).start();
        CompletableFuture<byte[]> stdout = CompletableFuture.supplyAsync(
                () -> readProcessStream(process.getInputStream())
        );
        CompletableFuture<byte[]> stderr = CompletableFuture.supplyAsync(
                () -> readProcessStream(process.getErrorStream())
        );
        if (!process.waitFor(Duration.ofSeconds(15).toMillis(), TimeUnit.MILLISECONDS)) {
            process.destroyForcibly();
            throw new ReviewConflict("Git 校验超时");
        }
        return new GitResult(
                process.exitValue(),
                new String(stdout.get(), StandardCharsets.UTF_8),
                new String(stderr.get(), StandardCharsets.UTF_8)
        );
    }

    private static byte[] readProcessStream(InputStream input) {
        try {
            return input.readAllBytes();
        } catch (IOException error) {
            throw new RuntimeException(error);
        }
    }

    private static void requireGitSuccess(GitResult result, String message) {
        if (result.exitCode() != 0) {
            throw new ReviewConflict(message + "：" + result.stderr().trim());
        }
    }

    private static String sha256(String value) {
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256")
                    .digest(value.getBytes(StandardCharsets.UTF_8));
            return java.util.HexFormat.of().formatHex(digest);
        } catch (NoSuchAlgorithmException error) {
            throw new IllegalStateException(error);
        }
    }

    private static String safeMessage(Exception error) {
        return error.getMessage() == null ? error.getClass().getSimpleName() : error.getMessage();
    }

    private static JsonObject error(String message) {
        JsonObject result = new JsonObject();
        result.addProperty("error", message == null ? "未知错误" : message);
        return result;
    }

    private static void respond(
            HttpExchange exchange,
            int status,
            JsonObject payload,
            String origin
    ) throws IOException {
        addCors(exchange.getResponseHeaders(), origin);
        byte[] body = GSON.toJson(payload).getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().set("Content-Type", "application/json; charset=utf-8");
        exchange.getResponseHeaders().set("Cache-Control", "no-store");
        exchange.sendResponseHeaders(status, body.length);
        exchange.getResponseBody().write(body);
        exchange.close();
    }

    @Override
    public void dispose() {
        if (server != null) {
            server.stop(0);
        }
        executor.shutdownNow();
    }

    private record RequestContext(
            Project project,
            Path root,
            Path target,
            int line,
            int editorColumn
    ) {
    }

    private record ReferenceResult(String path, int line, int column, String preview) {
        String key() {
            return path + ":" + line + ":" + column;
        }

        JsonObject toJson() {
            JsonObject result = new JsonObject();
            result.addProperty("path", path);
            result.addProperty("line", line);
            result.addProperty("column", column);
            result.addProperty("preview", preview);
            return result;
        }
    }

    private record GitResult(int exitCode, String stdout, String stderr) {
    }

    private static final class ReviewConflict extends RuntimeException {
        ReviewConflict(String message) {
            super(message);
        }
    }
}
