import type { AppConfig, Task } from "../types";
import type { CreateTaskDefaults } from "./appDataService";

export const MAX_TASK_TITLE_LENGTH = 50;

export function sortTasks(tasks: Task[]): Task[] {
  return [...tasks].sort((a, b) => {
    if (a.pinned !== b.pinned) return a.pinned ? -1 : 1;
    return new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime();
  });
}

/** Most recently updated task, ignoring pin order (for entry / delete fallback). */
export function mostRecentlyUpdatedTask(tasks: Task[]): Task | null {
  if (tasks.length === 0) return null;
  return [...tasks].sort(
    (a, b) =>
      new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime(),
  )[0];
}

export function titleFromPrompt(prompt: string): string {
  return prompt.trim().slice(0, MAX_TASK_TITLE_LENGTH) || "New task";
}

function resolveDefaultModel(config: AppConfig): string {
  const gatewayModels = config.gateway_models ?? [];
  if (gatewayModels.length > 0) {
    const candidate = config.default_gateway_model ?? config.default_model;
    if (gatewayModels.includes(candidate)) return candidate;
    return gatewayModels[0];
  }
  return config.default_model;
}

export function buildNewTaskDefaults(
  config: AppConfig,
  _activeTask: Task | null = null,
): CreateTaskDefaults {
  // Model / Guardrail / Memory / Skill / MCP all come from per-user
  // settings.json via /api/config — not from the active task.
  return {
    model_name: resolveDefaultModel(config),
    skills: config.default_skills ?? [],
    mcp_servers: config.default_mcp_servers ?? [],
    guardrail_enabled: config.default_guardrail_enabled ?? false,
    memory_enabled: config.default_memory_enabled ?? true,
  };
}

export function buildFallbackTaskDefaults(config: AppConfig): CreateTaskDefaults {
  return buildNewTaskDefaults(config);
}

export function applyTaskTitleFromPrompt(
  tasks: Task[],
  taskId: string,
  prompt: string,
): Task[] {
  return sortTasks(
    tasks.map((task) =>
      task.id === taskId && (task.title === "New task" || !task.title)
        ? {
            ...task,
            title: titleFromPrompt(prompt),
            updated_at: new Date().toISOString(),
          }
        : task,
    ),
  );
}
