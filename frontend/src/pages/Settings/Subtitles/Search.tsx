import { FunctionComponent } from "react";
import {
  Check,
  Chips,
  CollapseBox,
  Layout,
  Message,
  Number,
  Password,
  Section,
  Selector,
  Slider,
} from "@/pages/Settings/components";
import {
  adaptiveSearchingDelayOption,
  adaptiveSearchingDeltaOption,
  forcedOnlySearchOption,
} from "./options";

const SettingsSubtitlesSearchView: FunctionComponent = () => {
  return (
    <Layout name="Subtitles">
      <Section header="Upgrading Subtitles">
        <Check
          label="Upgrade Previously Downloaded Subtitles"
          settingKey="settings-general-upgrade_subs"
        ></Check>
        <Message>
          Schedule a task to upgrade subtitles previously downloaded by Bazarr.
        </Message>
        <CollapseBox settingKey="settings-general-upgrade_subs">
          <Slider
            settingKey="settings-general-days_to_upgrade_subs"
            max={30}
            mb="lg"
          ></Slider>
          <Message>
            Number of days to go back in history to upgrade subtitles.
          </Message>
          <Check
            label="Upgrade Manually Downloaded or Translated Subtitles"
            settingKey="settings-general-upgrade_manual"
          ></Check>
          <Message>
            Enable or disable upgrade of manually downloaded or translated
            subtitles.
          </Message>
        </CollapseBox>
      </Section>
      <Section header="Search Scores">
        <Slider
          label="Minimum Score For Episodes"
          settingKey="settings-general-minimum_score"
        ></Slider>
        <Slider
          label="Minimum Score For Movies"
          settingKey="settings-general-minimum_score_movie"
        ></Slider>
        <Message>
          Subtitles with a score below the minimum will not be downloaded
          automatically.
        </Message>
      </Section>
      <Section header="Performance / Optimization">
        <Check
          label="Adaptive Searching"
          settingKey="settings-general-adaptive_searching"
        ></Check>
        <Message>
          When enabled, Bazarr will skip searching providers for subtitles which
          have been searched recently.
        </Message>
        <CollapseBox settingKey="settings-general-adaptive_searching">
          <Selector
            settingKey="settings-general-adaptive_searching_delay"
            settingOptions={{ onSaved: (v) => (v === undefined ? "3w" : v) }}
            options={adaptiveSearchingDelayOption}
          ></Selector>
          <Message>
            The delay from the first search to adaptive searching taking effect.
            During this time window Bazarr will continue to search for
            subtitles, even if they have been searched for recently.
          </Message>
          <Selector
            settingKey="settings-general-adaptive_searching_delta"
            settingOptions={{ onSaved: (v) => (v === undefined ? "1w" : v) }}
            options={adaptiveSearchingDeltaOption}
          ></Selector>
          <Message>
            The delay between Bazarr searching for subtitles in adaptive search
            mode. If the media has been searched for more recently than this
            value, Bazarr will skip searching for subtitles.
          </Message>
        </CollapseBox>
        <Selector
          label="Search For Forced-Only Subtitles"
          settingKey="settings-general-forced_only_search_days"
          settingOptions={{ onSaved: (v) => (v === undefined ? 0 : v) }}
          options={forcedOnlySearchOption}
        ></Selector>
        <Message>
          Forced subtitles only exist for some movies and episodes. They are
          always searched together with other missing languages, but when forced
          subtitles are the only thing missing they are searched at most this
          often (new media is always searched once).
        </Message>
        <Check
          label="Only Want Forced Subtitles For Titles That Have Them"
          settingKey="settings-general-forced_only_when_available"
        ></Check>
        <Message>
          Forced subtitles only exist for titles with foreign-language parts.
          Series and movies without any forced subtitle stop being wanted for
          forced subtitles: those TMDB lists with a single spoken language, or
          those already searched without finding any. They are wanted again as
          soon as a forced subtitle is found for them.
        </Message>
        <CollapseBox settingKey="settings-general-forced_only_when_available">
          <Check
            label="Use TMDB Spoken Languages"
            settingKey="settings-general-forced_evidence_use_tmdb"
          ></Check>
          <Message>
            Titles where TMDB lists more than one spoken language keep wanting
            forced subtitles, titles with a single one don't.
          </Message>
          <Number
            label="Grace Period (Days)"
            settingKey="settings-general-forced_evidence_grace_days"
            min={0}
            max={365}
          ></Number>
          <Message>
            Without TMDB information, how long after forced subtitles were first
            searched for a title before it stops wanting them.
          </Message>
          <Password
            label="TMDB API Key (Optional)"
            settingKey="settings-general-tmdb_api_key"
          ></Password>
          <Message>Leave empty to use the key bundled with Bazarr.</Message>
        </CollapseBox>
        <Check
          label="Search Enabled Providers Simultaneously"
          settingKey="settings-general-multithreading"
        ></Check>
        <Message>
          Search multiple providers at once. (Don't choose this on low powered
          devices).
        </Message>
        <Check
          label="Search Each Provider Once For All Missing Languages"
          settingKey="settings-general-shared_provider_discovery"
        ></Check>
        <Message>
          Ask every provider once for all the missing subtitles of a movie or
          episode instead of once per missing language. Each language is still
          scored and chosen on its own, and cutoff is still respected. Reduces
          provider requests for profiles with multiple languages.
        </Message>
        <Check
          label="Skip video file hash calculation"
          settingKey="settings-general-skip_hashing"
        ></Check>
        <Message>
          Skip video file hashing during search process to prevent a sleeping
          hard disk drive from waking up. However, this may decrease your search
          results scores.
        </Message>
      </Section>
      <Section header="Subtitle Packs">
        <Check
          label="Reuse Subtitle Packs Across Episodes"
          settingKey="settings-general-pack_reuse"
        ></Check>
        <Message>
          When a provider offers a season or multi-episode pack, download the
          whole pack once and use it to fill every wanted episode it contains
          instead of downloading one file per episode. Each episode is still
          scored and checked against its language profile. Currently supported
          by SubDL.
        </Message>
      </Section>
      <Section header="Wanted Performance">
        <Check
          label="Search Multiple Wanted Items At Once"
          settingKey="settings-general-wanted_parallel_enabled"
        ></Check>
        <Message>
          Search several wanted episodes and movies at the same time, each one
          provider at a time, keeping the first subtitle that meets the minimum
          score instead of waiting for every provider. Better subtitles are
          found later by "Upgrade Previously Downloaded Subtitles", which should
          be enabled. Provider limits below apply to every search while this is
          enabled.
        </Message>
        <CollapseBox settingKey="settings-general-wanted_parallel_enabled">
          <Number
            label="Items Searched At Once"
            settingKey="settings-general-wanted_max_active_items"
            min={1}
            max={64}
          ></Number>
          <Message>
            Maximum number of wanted episodes or movies being searched at the
            same time by each wanted job. Concurrent Jobs limits jobs, not items
            or provider requests.
          </Message>
          <Number
            label="Default Simultaneous Requests Per Provider"
            settingKey="settings-general-provider_default_max_in_flight"
            min={1}
            max={16}
          ></Number>
          <Message>
            How many searches or downloads a provider can handle at once, unless
            overridden below. Keep it at 1 for providers with strict limits.
          </Message>
          <Chips
            label="Provider Limits"
            settingKey="settings-general-provider_limits"
            sanitizeFn={(values: string[] | null) =>
              values?.map((item) =>
                item.replace(/[^a-z0-9_:]/gi, "").toLowerCase(),
              )
            }
          ></Chips>
          <Message>
            Per provider overrides written as provider:requests or
            provider:requests:milliseconds between requests, for example
            gestdown:2 or tvsubtitles:1:2000.
          </Message>
        </CollapseBox>
      </Section>
    </Layout>
  );
};

export default SettingsSubtitlesSearchView;
