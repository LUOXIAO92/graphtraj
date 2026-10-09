/** Bundled primary-source snapshot; opening the dashboard never fetches prices. */
export type Price = {
  id: string; vendor: string; models: string[]; modelVersion: string; currency: 'USD'; unit: '1M tokens';
  verified: string; source: string; effectiveFrom: string | null; effectiveTo?: string;
  input: number; cacheRead: number; cacheWrite: number | null; output: number;
  rules: string; peak?: { input: number; cacheRead: number; output: number };
  longContext?: { threshold: number; inputMultiplier: number; outputMultiplier: number };
};
export const prices: Price[] = [
  { id: 'openai-astra-2026-10-10', vendor: 'OpenAI', models: ['gpt-6-astra'], modelVersion: 'gpt-6-astra',
    currency: 'USD', unit: '1M tokens', verified: '2026-10-10', effectiveFrom: null,
    source: 'https://developers.openai.com/api/docs/models/gpt-6-astra',
    input: 10, cacheRead: 1, cacheWrite: 12.5, output: 50,
    longContext: { threshold: 272000, inputMultiplier: 2, outputMultiplier: 1.5 },
    rules: 'Standard-tier equivalent. >272K input: 2× input/cache and 1.5× output. Cache writes replace ordinary input rates. Reasoning is included in output. Actual Batch/Flex 0.5×, Fast 2×, Ultrafast 6× and regional/FedRAMP 1.1× are not inferred from missing routing metadata. Effective start not published in snapshot; current-rate approximation.',
  },
  { id: 'openai-codex-2026-10-10', vendor: 'OpenAI', models: ['gpt-5.3-codex'], modelVersion: 'gpt-5.3-codex',
    currency: 'USD', unit: '1M tokens', verified: '2026-10-10', effectiveFrom: null,
    source: 'https://developers.openai.com/api/docs/pricing', input: 1.75, cacheRead: 0.175, cacheWrite: null, output: 14,
    rules: 'Standard-tier equivalent; Fast is 2×. No separate cache-write rate for this earlier model. Reasoning included in output. Unknown routing/region not inferred. Effective start unverified; current-rate approximation.',
  },
  { id: 'deepseek-flash-2026-10-10', vendor: 'DeepSeek',
    models: ['deepseek-flash', 'deepseek-v4-flash', 'deepseek-v4-flash-vision-exp'], modelVersion: 'DeepSeek-V4.1-Flash',
    currency: 'USD', unit: '1M tokens', verified: '2026-10-10', effectiveFrom: null,
    source: 'https://api-docs.deepseek.com/quick_start/pricing/', input: 0.15, cacheRead: 0.003, cacheWrite: null, output: 0.6,
    peak: { input: 0.3, cacheRead: 0.006, output: 1.2 },
    rules: 'Off-peak rates. Peak UTC Mon–Fri 01–04 and 06–10 except Chinese public holidays: 2×. Weekday peak windows remain unpriced without verified holiday applicability. Cache writes have no separate charge. Thinking included in output. Legacy Flash aliases currently route to V4.1; earlier calls are current-model/current-rate approximations. Effective start unverified.',
  },
  { id: 'deepseek-pro-2026-10-10', vendor: 'DeepSeek', models: ['deepseek-v4-pro'], modelVersion: 'DeepSeek-V4-Pro-0813',
    currency: 'USD', unit: '1M tokens', verified: '2026-10-10', effectiveFrom: null,
    source: 'https://api-docs.deepseek.com/quick_start/pricing/', input: 0.66, cacheRead: 0.022, cacheWrite: null, output: 1.98,
    peak: { input: 1.32, cacheRead: 0.044, output: 3.96 },
    rules: 'Off-peak rates; same UTC peak/holiday rule as Flash. Weekday peak windows unpriced without verified holiday applicability. Cache writes included in ordinary input; thinking included in output. Effective start unverified; current-rate approximation.',
  },
];
