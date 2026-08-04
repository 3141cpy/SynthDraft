import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import SettingsPage from "../page";
import {
  activateAIConfig,
  createAIConfig,
  getAIConfigs,
  testAIConfig,
} from "@/lib/api";
import type { AIProviderConfig } from "@/lib/types";

// ===== Mocks =====
// mock 整个 api 模块，避免真实网络请求；组件用到下列 4 个函数。
// deleteAIConfig / updateAIConfig 由 ProviderConfigCard / ProviderConfigForm
// 触发，被 mock 以保持单元隔离，但本页面级测试不再直接断言。
vi.mock("@/lib/api", () => ({
  getAIConfigs: vi.fn(),
  createAIConfig: vi.fn(),
  updateAIConfig: vi.fn(),
  deleteAIConfig: vi.fn(),
  activateAIConfig: vi.fn(),
  testAIConfig: vi.fn(),
}));

// mock sonner toast，避免在 jsdom 中渲染 Toaster 门户。
vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
    warning: vi.fn(),
  },
}));

// ===== Fixtures =====
function makeConfig(
  overrides: Partial<AIProviderConfig> = {},
): AIProviderConfig {
  return {
    id: 1,
    name: "本地 Ollama",
    provider_type: "ollama",
    base_url: "http://localhost:11434",
    api_key: "",
    model: "qwen2.5-coder:7b",
    vlm_model: "",
    is_active: false,
    created_at: "2024-01-01T00:00:00Z",
    updated_at: "2024-01-01T00:00:00Z",
    ...overrides,
  };
}

// ===== Setup / Teardown =====
beforeEach(() => {
  // 默认返回空配置列表，各测试可按需覆盖。
  vi.mocked(getAIConfigs).mockResolvedValue([]);
});

afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

// ===== 1. 页面渲染测试 =====
describe("页面渲染", () => {
  it("renders settings page with title", async () => {
    render(<SettingsPage />);
    expect(
      screen.getByRole("heading", { name: "设置" }),
    ).toBeInTheDocument();
    expect(screen.getByText("AI Provider 配置")).toBeInTheDocument();
  });

  it("shows loading state initially", async () => {
    // getAIConfigs 永不 resolve，保持 loading 状态
    vi.mocked(getAIConfigs).mockImplementation(
      () => new Promise<AIProviderConfig[]>(() => {}),
    );
    render(<SettingsPage />);
    expect(screen.getByText("正在加载配置列表...")).toBeInTheDocument();
  });

  it("shows empty state when no configs", async () => {
    render(<SettingsPage />);
    expect(await screen.findByText("暂无 AI 配置")).toBeInTheDocument();
  });

  it("shows error state on fetch failure", async () => {
    vi.mocked(getAIConfigs).mockRejectedValue(new Error("网络错误"));
    render(<SettingsPage />);
    expect(await screen.findByText("加载失败")).toBeInTheDocument();
    expect(await screen.findByText("网络错误")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "重试" }),
    ).toBeInTheDocument();
  });
});

// ===== 2. 配置列表测试 =====
describe("配置列表", () => {
  it("renders config cards when configs exist", async () => {
    const c1 = makeConfig({ id: 1, name: "本地 Ollama" });
    const c2 = makeConfig({ id: 2, name: "远程 OpenAI" });
    vi.mocked(getAIConfigs).mockResolvedValue([c1, c2]);
    render(<SettingsPage />);
    expect(await screen.findByText("本地 Ollama")).toBeInTheDocument();
    expect(screen.getByText("远程 OpenAI")).toBeInTheDocument();
  });

  it("displays provider type badge", async () => {
    vi.mocked(getAIConfigs).mockResolvedValue([
      makeConfig({ provider_type: "ollama" }),
    ]);
    render(<SettingsPage />);
    expect(await screen.findByText("Ollama")).toBeInTheDocument();
  });

  it("displays active badge for active config", async () => {
    vi.mocked(getAIConfigs).mockResolvedValue([
      makeConfig({ is_active: true }),
    ]);
    render(<SettingsPage />);
    expect(await screen.findByText("活跃")).toBeInTheDocument();
  });
});

// ===== 3. 新增配置表单测试 =====
describe("新增配置表单", () => {
  it("opens create form on button click", async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    render(<SettingsPage />);
    await screen.findByText("暂无 AI 配置");
    // 空状态下页面有多个「新增配置」按钮，点击任一即可打开表单
    const buttons = screen.getAllByRole("button", { name: "新增配置" });
    await user.click(buttons[0]);
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toBeInTheDocument();
    // 表单描述为对话框内唯一文本，确认表单已打开
    expect(within(dialog).getByText(/填写 Provider 信息/)).toBeInTheDocument();
  });

  it("auto-fills base_url when provider type selected", async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    render(<SettingsPage />);
    await screen.findByText("暂无 AI 配置");
    const buttons = screen.getAllByRole("button", { name: "新增配置" });
    await user.click(buttons[0]);
    await screen.findByRole("dialog");
    const baseUrlInput = screen.getByLabelText("Base URL");
    // 默认 provider=ollama，base_url 自动填充为 ollama 默认地址
    expect(baseUrlInput).toHaveValue("http://localhost:11434");
    // 切换为 Anthropic，base_url 应自动更新
    await user.click(
      screen.getByRole("combobox", { name: "Provider 类型" }),
    );
    await user.click(
      await screen.findByRole("option", { name: "Anthropic Claude" }),
    );
    expect(baseUrlInput).toHaveValue("https://api.anthropic.com");
  });

  it("validates required fields", async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    render(<SettingsPage />);
    await screen.findByText("暂无 AI 配置");
    const buttons = screen.getAllByRole("button", { name: "新增配置" });
    await user.click(buttons[0]);
    const dialog = await screen.findByRole("dialog");
    // 清空默认 base_url，触发 base_url 必填校验
    await user.clear(screen.getByLabelText("Base URL"));
    // name / model 留空，直接提交
    await user.click(
      within(dialog).getByRole("button", { name: "新增配置" }),
    );
    expect(await screen.findByText("请填写配置名称")).toBeInTheDocument();
    expect(screen.getByText("请填写 Base URL")).toBeInTheDocument();
    expect(screen.getByText("请填写模型名称")).toBeInTheDocument();
    expect(createAIConfig).not.toHaveBeenCalled();
  });

  it("submits form with correct payload", async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    vi.mocked(createAIConfig).mockResolvedValue(makeConfig());
    render(<SettingsPage />);
    await screen.findByText("暂无 AI 配置");
    const buttons = screen.getAllByRole("button", { name: "新增配置" });
    await user.click(buttons[0]);
    const dialog = await screen.findByRole("dialog");
    await user.type(screen.getByLabelText("配置名称"), "测试配置");
    await user.type(screen.getByLabelText("模型名称"), "qwen2.5-coder:7b");
    await user.click(
      within(dialog).getByRole("button", { name: "新增配置" }),
    );
    await waitFor(() => expect(createAIConfig).toHaveBeenCalledTimes(1));
    expect(createAIConfig).toHaveBeenCalledWith({
      name: "测试配置",
      provider_type: "ollama",
      base_url: "http://localhost:11434",
      api_key: "",
      model: "qwen2.5-coder:7b",
      vlm_model: "",
    });
  });
});

// ===== 4. 测试连接交互测试 =====
describe("测试连接", () => {
  beforeEach(() => {
    // 这一组测试需要一张已存在的配置卡片
    vi.mocked(getAIConfigs).mockResolvedValue([makeConfig()]);
  });

  it("calls testAIConfig on test button click", async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    vi.mocked(testAIConfig).mockResolvedValue({
      available: true,
      vlm_available: false,
      latency_ms: 100,
      error: "",
    });
    render(<SettingsPage />);
    await screen.findByText("本地 Ollama");
    await user.click(screen.getByRole("button", { name: "测试连接" }));
    await waitFor(() => expect(testAIConfig).toHaveBeenCalledWith(1));
  });

  it("shows success result with latency", async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    vi.mocked(testAIConfig).mockResolvedValue({
      available: true,
      vlm_available: false,
      latency_ms: 120,
      error: "",
    });
    render(<SettingsPage />);
    await screen.findByText("本地 Ollama");
    await user.click(screen.getByRole("button", { name: "测试连接" }));
    expect(await screen.findByText("连接成功")).toBeInTheDocument();
    expect(screen.getByText(/延迟 120ms/)).toBeInTheDocument();
  });

  it("shows failure result with error", async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    vi.mocked(testAIConfig).mockResolvedValue({
      available: false,
      vlm_available: false,
      latency_ms: 0,
      error: "connection refused",
    });
    render(<SettingsPage />);
    await screen.findByText("本地 Ollama");
    await user.click(screen.getByRole("button", { name: "测试连接" }));
    expect(await screen.findByText("连接失败")).toBeInTheDocument();
    expect(screen.getByText("connection refused")).toBeInTheDocument();
  });
});

// ===== 5. 激活 / 删除测试 =====
describe("激活与删除", () => {
  beforeEach(() => {
    vi.mocked(getAIConfigs).mockResolvedValue([makeConfig()]);
  });

  it("calls activateAIConfig on activate button click", async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    vi.mocked(activateAIConfig).mockResolvedValue(
      makeConfig({ is_active: true }),
    );
    render(<SettingsPage />);
    await screen.findByText("本地 Ollama");
    await user.click(screen.getByRole("button", { name: "激活" }));
    await waitFor(() => expect(activateAIConfig).toHaveBeenCalledWith(1));
  });

  it("shows delete confirmation dialog", async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    render(<SettingsPage />);
    await screen.findByText("本地 Ollama");
    await user.click(screen.getByRole("button", { name: "删除" }));
    const alert = await screen.findByRole("alertdialog");
    expect(within(alert).getByText("确认删除配置")).toBeInTheDocument();
  });
});
