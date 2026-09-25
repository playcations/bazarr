import userEvent from "@testing-library/user-event";
import { Mock, vi, vitest } from "vitest";
import {
  useClearCache,
  useSettingsMutation,
  useSystemCache,
  useSystemSettings,
} from "@/apis/hooks";
import { customRender, screen } from "@/tests";
import SettingsSchedulerView from ".";

vi.mock("@/apis/hooks", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/apis/hooks")>();
  return {
    ...actual,
    useSystemSettings: vitest.fn(),
    useSettingsMutation: vitest.fn(),
    useSystemCache: vitest.fn(),
    useClearCache: vitest.fn(),
  };
});

const clearCache = vitest.fn();

const renderPage = () => {
  (useSystemSettings as Mock).mockReturnValue({
    data: { general: {}, backup: {}, cache: {} } as unknown as Settings,
    isLoading: false,
    isRefetching: false,
  });
  (useSettingsMutation as Mock).mockReturnValue({
    mutate: vitest.fn(),
    isPending: false,
  });
  (useSystemCache as Mock).mockReturnValue({
    data: { files: 12, size: "3.4 MB" },
  });
  (useClearCache as Mock).mockReturnValue({
    mutate: clearCache,
    isPending: false,
  });
  return customRender(<SettingsSchedulerView />);
};

describe("SettingsSchedulerView cache section", () => {
  beforeEach(() => {
    vitest.clearAllMocks();
  });

  it("should show the cache size and settings", () => {
    renderPage();

    expect(screen.getByText("Reuse Search Results For")).toBeInTheDocument();
    expect(screen.getByText("12 files, 3.4 MB")).toBeInTheDocument();
  });

  it("should clear cached search results or the whole cache", async () => {
    renderPage();

    await userEvent.click(screen.getByText("Clear Search Results"));
    expect(clearCache).toHaveBeenCalledWith("search");

    await userEvent.click(screen.getByText("Clear Entire Cache"));
    expect(clearCache).toHaveBeenCalledWith("all");
  });
});
