import { fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Mock, vi, vitest } from "vitest";
import { useSettingsMutation, useSystemSettings } from "@/apis/hooks";
import { customRender, screen } from "@/tests";
import SettingsSubtitlesSearchView from "./Search";

vi.mock("@/apis/hooks", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/apis/hooks")>();
  return {
    ...actual,
    useSystemSettings: vitest.fn(),
    useSettingsMutation: vitest.fn(),
  };
});

const mockedUseSystemSettings = useSystemSettings as Mock;
const mockedUseSettingsMutation = useSettingsMutation as Mock;

const baseSettings = {
  general: {
    theme: "auto",
    instance_name: "Bazarr",
    adaptive_searching: true,
    upgrade_subs: true,
  },
} as unknown as Settings;

const setupMocks = () => {
  mockedUseSystemSettings.mockReturnValue({
    data: baseSettings,
    isLoading: false,
    isRefetching: false,
  });
  mockedUseSettingsMutation.mockReturnValue({
    mutate: vitest.fn(),
    isPending: false,
  });
};

const renderPage = () => {
  setupMocks();
  return customRender(<SettingsSubtitlesSearchView />);
};

describe("SettingsSubtitlesSearchView", () => {
  beforeEach(() => {
    vitest.clearAllMocks();
  });

  it("should render the shared provider discovery option", () => {
    renderPage();

    expect(
      screen.getByText("Search Each Provider Once For All Missing Languages"),
    ).toBeInTheDocument();
  });

  it("should render the subtitle packs option", () => {
    renderPage();

    expect(
      screen.getByText("Reuse Subtitle Packs Across Episodes"),
    ).toBeInTheDocument();
  });

  it("should render the parallel wanted option", () => {
    renderPage();

    expect(
      screen.getByText("Search Multiple Wanted Items At Once"),
    ).toBeInTheDocument();
  });

  it("should render the forced-only search option", () => {
    renderPage();

    expect(
      screen.getByText("Search For Forced-Only Subtitles"),
    ).toBeInTheDocument();
  });

  it("should render the forced subtitles evidence option", () => {
    renderPage();

    expect(
      screen.getByText("Only Want Forced Subtitles For Titles That Have Them"),
    ).toBeInTheDocument();
  });

  it("should render expanded search sections", () => {
    renderPage();

    expect(
      screen.getByText(
        /Number of days to go back in history to upgrade subtitles/i,
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        /The delay from the first search to adaptive searching taking effect/i,
      ),
    ).toBeInTheDocument();
  });

  it("should trigger onSaved when selecting adaptive searching delay", async () => {
    renderPage();

    const selects = screen.getAllByTestId("input-selector");
    const delaySelect = selects[0];

    await userEvent.click(delaySelect);

    const options = screen.getAllByRole("option", {
      hidden: true,
      name: "3 weeks",
    });

    fireEvent.click(options[0]);

    expect(delaySelect).toHaveValue("3 weeks");
  });

  it("should trigger onSaved when selecting adaptive searching delta", async () => {
    renderPage();

    const selects = screen.getAllByTestId("input-selector");
    const deltaSelect = selects[1];

    await userEvent.click(deltaSelect);

    const option = screen.getByRole("option", { hidden: true, name: "3 days" });

    fireEvent.click(option);

    expect(deltaSelect).toHaveValue("3 days");
  });
});
