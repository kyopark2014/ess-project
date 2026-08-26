import type { AppConfig, Task } from "../types";
import type { CreateTaskDefaults } from "./appDataService";

export const MAX_TASK_TITLE_LENGTH = 50;

export function sortTasks(tasks: Task[]): Task[] {
  return [...tasks].sort((a, b) => {
    if (a.pinned !== b.pinned) return a.pinned ? -1 : 1;
    return new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime();
  });
}

export function titleFromPrompt(prompt: string): string {
  return prompt.trim().slice(0, MAX_TASK_TITLE_LENGTH) || "New task";
}

function resolveDefaultModel(config: AppConfig, activeTask: Task | null): string {
  const gatewayModels = config.gateway_models ?? [];
  if (gatewayModels.length > 0) {
    const candidate =
      activeTask?.model_name ??
      config.default_gateway_model ??
      config.default_model;
    if (gatewayModels.includes(candidate)) return candidate;
    return gatewayModels[0];
  }
  return activeTask?.model_name ?? config.default_model;
}

export function buildNewTaskDefaults(
  config: AppConfig,
  activeTask: Task | null,
): CreateTaskDefaults {
  return {
    model_name: resolveDefaultModel(config, activeTask),
    skills: config.default_skills ?? [],
    mcp_servers: config.default_mcp_servers ?? [],
    guardrail_enabled: activeTask?.guardrail_enabled ?? false,
    memory_enabled: activeTask?.memory_enabled ?? true,
  };
}

export function buildFallbackTaskDefaults(config: AppConfig): CreateTaskDefaults {
  const gatewayModels = config.gateway_models ?? [];
  const model_name =
    gatewayModels.length > 0
      ? (config.default_gateway_model &&
        gatewayModels.includes(config.default_gateway_model)
          ? config.default_gateway_model
          : gatewayModels[0])
      : config.default_model;
  return {
    model_name,
    skills: config.default_skills,
    mcp_servers: config.default_mcp_servers,
    memory_enabled: true,
  };
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
