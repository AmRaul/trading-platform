'use client';

import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import Navbar from '@/components/Navbar';
import { authApi, meApi, type Me } from '@/lib/api';
import { apiErrorText } from '@/lib/types';

const MODES: { key: Me['telegram']['notify']; label: string; hint: string }[] = [
  { key: 'all', label: 'Все боты', hint: 'входы, доборы, выходы и проблемы — и реальных, и бумажных ботов' },
  { key: 'real', label: 'Только реальные', hint: 'бумажные боты (paper) молчат' },
  { key: 'off', label: 'Выключено', hint: 'ничего не присылать' },
];

export default function SettingsPage() {
  const qc = useQueryClient();
  const { data: me, isLoading, error } = useQuery<Me>({
    queryKey: ['me'],
    queryFn: async () => (await meApi.get()).data,
  });
  const [link, setLink] = useState<{ code: string; url: string | null; bot_username: string | null } | null>(null);
  const [tgError, setTgError] = useState<string | null>(null);

  // пока ждём «Start» в Telegram — проверяем привязку раз в 3 с
  const waiting = !!link && (!me?.telegram.linked || me.telegram.via_owner_chat);
  useEffect(() => {
    if (!waiting) return;
    const t = setInterval(() => qc.invalidateQueries({ queryKey: ['me'] }), 3000);
    return () => clearInterval(t);
  }, [waiting, qc]);
  useEffect(() => {
    if (me?.telegram.linked && !me.telegram.via_owner_chat) setLink(null);
  }, [me?.telegram.linked, me?.telegram.via_owner_chat]);

  const makeLink = useMutation({
    mutationFn: async () => (await meApi.telegramLink()).data,
    onSuccess: (d) => { setLink(d); setTgError(null); },
    onError: (e) => setTgError(apiErrorText(e)),
  });
  const setMode = useMutation({
    mutationFn: (notify: Me['telegram']['notify']) => meApi.telegramSettings(notify),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['me'] }),
    onError: (e) => setTgError(apiErrorText(e)),
  });
  const unlink = useMutation({
    mutationFn: () => meApi.telegramUnlink(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['me'] }),
  });

  const [pw, setPw] = useState({ old: '', next: '', repeat: '' });
  const [pwMsg, setPwMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const changePw = useMutation({
    mutationFn: () => authApi.changePassword(pw.old, pw.next),
    onSuccess: () => {
      setPw({ old: '', next: '', repeat: '' });
      setPwMsg({ ok: true, text: 'Пароль изменён. На других устройствах нужно войти заново.' });
    },
    onError: (e) => setPwMsg({ ok: false, text: apiErrorText(e) }),
  });

  const input = 'w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-blue-500';
  const tg = me?.telegram;

  return (
    <div className="min-h-screen bg-gray-900 text-white">
      <Navbar />
      <div className="max-w-2xl mx-auto px-4 py-8 space-y-6">
        <h1 className="text-3xl font-bold">Настройки</h1>
        {isLoading && <p className="text-gray-400">Загрузка…</p>}
        {error && <p className="text-red-400">{apiErrorText(error)}</p>}

        {me && (
          <>
            <section className="bg-gray-800 rounded-lg border border-gray-700 p-5">
              <h2 className="text-lg font-semibold mb-1">Аккаунт</h2>
              <p className="text-sm text-gray-400">
                {me.username}{me.is_admin && ' · администратор'} · ботов {me.bots.count}
                {me.bots.limit != null ? ` из ${me.bots.limit}` : ' (без лимита)'}
              </p>
            </section>

            <section className="bg-gray-800 rounded-lg border border-gray-700 p-5 space-y-4">
              <div>
                <h2 className="text-lg font-semibold">Telegram</h2>
                <p className="text-sm text-gray-400">
                  Входы, доборы, выходы с PnL и проблемы ваших ботов — в ваш личный чат с ботом kandle.
                </p>
              </div>

              {!tg?.available && <p className="text-yellow-400 text-sm">Telegram-бот на сервере не настроен.</p>}

              {tg?.available && tg.linked && (
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <span className="text-green-400 text-sm">
                    {tg.via_owner_chat ? 'Подключён общий чат владельца (TELEGRAM_CHAT_ID)' : 'Подключено'}
                  </span>
                  {tg.via_owner_chat ? (
                    <button onClick={() => makeLink.mutate()} disabled={makeLink.isPending}
                      className="px-3 py-1.5 rounded bg-gray-700 hover:bg-gray-600 text-sm">
                      Подключить личный чат
                    </button>
                  ) : (
                    <button onClick={() => unlink.mutate()} disabled={unlink.isPending}
                      className="px-3 py-1.5 rounded bg-gray-700 hover:bg-red-800 text-sm">Отключить</button>
                  )}
                </div>
              )}

              {tg?.available && !tg.linked && !link && (
                <button onClick={() => makeLink.mutate()} disabled={makeLink.isPending}
                  className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 font-medium disabled:opacity-50">
                  Подключить Telegram
                </button>
              )}

              {link && (
                <div className="bg-gray-900/60 rounded-lg p-4 text-sm space-y-2">
                  {link.url ? (
                    <>
                      <p>Откройте бота и нажмите <b>Start</b> — чат привяжется сам (ссылка действует 15 минут):</p>
                      <a href={link.url} target="_blank" rel="noreferrer"
                        className="inline-block px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 font-medium">
                        Открыть @{link.bot_username}
                      </a>
                    </>
                  ) : (
                    <p>Напишите боту kandle: <code className="bg-gray-800 px-1 rounded">/start {link.code}</code> (15 минут).</p>
                  )}
                  <p className="text-gray-400">Жду подтверждения из Telegram…</p>
                </div>
              )}

              {tg?.linked && (
                <div className="space-y-2">
                  <p className="text-sm text-gray-400">Что присылать:</p>
                  {MODES.map((m) => (
                    <label key={m.key} className="flex items-start gap-2 text-sm cursor-pointer">
                      <input type="radio" name="notify" checked={tg.notify === m.key}
                        onChange={() => setMode.mutate(m.key)} className="mt-1" />
                      <span><b>{m.label}</b> <span className="text-gray-400">— {m.hint}</span></span>
                    </label>
                  ))}
                </div>
              )}
              {tgError && <p className="text-red-400 text-sm">{tgError}</p>}
            </section>

            <section className="bg-gray-800 rounded-lg border border-gray-700 p-5">
              <h2 className="text-lg font-semibold mb-3">Смена пароля</h2>
              <form
                className="space-y-3"
                onSubmit={(e) => {
                  e.preventDefault();
                  if (pw.next !== pw.repeat) { setPwMsg({ ok: false, text: 'Новые пароли не совпадают' }); return; }
                  changePw.mutate();
                }}
              >
                <input type="password" required placeholder="Текущий пароль" value={pw.old}
                  onChange={(e) => setPw({ ...pw, old: e.target.value })} className={input} />
                <input type="password" required placeholder="Новый пароль" value={pw.next}
                  onChange={(e) => setPw({ ...pw, next: e.target.value })} className={input} />
                <input type="password" required placeholder="Новый пароль ещё раз" value={pw.repeat}
                  onChange={(e) => setPw({ ...pw, repeat: e.target.value })} className={input} />
                <p className="text-xs text-gray-500">Не короче 8 символов, заглавная и строчная буква, цифра.</p>
                {pwMsg && <p className={`text-sm ${pwMsg.ok ? 'text-green-400' : 'text-red-400'}`}>{pwMsg.text}</p>}
                <button type="submit" disabled={changePw.isPending}
                  className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 font-medium disabled:opacity-50">
                  Сменить пароль
                </button>
              </form>
            </section>
          </>
        )}
      </div>
    </div>
  );
}
