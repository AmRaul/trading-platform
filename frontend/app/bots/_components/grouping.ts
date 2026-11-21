import type { Bot } from '@/lib/types';

export type ExchangeTab = 'all' | 'paper' | 'bybit' | 'cryptorg';

export const EXCHANGE_TABS: { key: ExchangeTab; label: string }[] = [
  { key: 'all', label: 'Все' },
  { key: 'paper', label: 'Бумажные' },
  { key: 'bybit', label: 'Bybit' },
  { key: 'cryptorg', label: 'Cryptorg' },
];

export const TAB_STORAGE_KEY = 'bots-exchange-tab';

// Старые боты без exchange — Cryptorg (как и дефолт в форме редактирования)
export const botExchange = (bot: Bot): ExchangeTab => bot.exchange ?? 'cryptorg';

export const COLLAPSED_STORAGE_KEY = 'bots-collapsed-groups';
export const OTHER_GROUP = 'Отдельные боты';

export type BotGroup = { key: string; bots: Bot[] };

// «Шорт альтов · … · Консервативный · SOLUSDT» → «Шорт альтов · … · Консервативный»
const strategyOf = (bot: Bot): string => {
  const suffix = ` · ${bot.symbol}`;
  return bot.name.endsWith(suffix) ? bot.name.slice(0, -suffix.length) : bot.name;
};

// Боты одной стратегии — вместе; одиночные ручные боты (имя без « · ») — в «Отдельные боты», в конце
export function groupBots(list: Bot[]): BotGroup[] {
  const byKey = new Map<string, Bot[]>();
  for (const bot of list) {
    let key = strategyOf(bot);
    if (!key.includes(' · ') && list.filter((b) => strategyOf(b) === key).length < 2) key = OTHER_GROUP;
    byKey.set(key, [...(byKey.get(key) ?? []), bot]);
  }
  const groups = Array.from(byKey, ([key, bots]) => ({ key, bots }));
  return [...groups.filter((g) => g.key !== OTHER_GROUP), ...groups.filter((g) => g.key === OTHER_GROUP)];
}

// Внутри группы длинное имя стратегии не повторяем — в карточке только монета
export function cardTitle(bot: Bot, group: BotGroup): string {
  if (group.key === OTHER_GROUP) return bot.name;
  return bot.name === group.key ? bot.symbol : bot.name.slice(group.key.length + 3);
}

export const money = (n: number) => `${n >= 0 ? '+' : '−'}$${Math.abs(n).toFixed(2)}`;
