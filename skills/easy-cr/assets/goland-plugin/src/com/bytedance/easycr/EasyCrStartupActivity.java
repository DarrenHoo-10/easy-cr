package com.bytedance.easycr;

import com.intellij.openapi.application.ApplicationManager;
import com.intellij.openapi.project.Project;
import com.intellij.openapi.startup.ProjectActivity;
import kotlin.Unit;
import kotlin.coroutines.Continuation;
import org.jetbrains.annotations.NotNull;
import org.jetbrains.annotations.Nullable;

public final class EasyCrStartupActivity implements ProjectActivity {
    @Override
    public @Nullable Object execute(
            @NotNull Project project,
            @NotNull Continuation<? super Unit> continuation
    ) {
        ApplicationManager.getApplication().getService(EasyCrHttpService.class);
        return Unit.INSTANCE;
    }
}
