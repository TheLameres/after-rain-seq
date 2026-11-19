# Tasks

## 1. Ревью дельт на соответствие коду

- [ ] 1.1 Сверить дельту `harmony` с кодом (`src/harmony/`): состав ладов, войсинги, поведение degree_to_note; исправить расхождения; проверить `openspec validate init-current-system --strict`
- [ ] 1.2 Сверить дельту `track-graph` с кодом (`src/session/model/`, `src/session/graph/`, `src/session/session.py`): лимиты 16/2/2, стратегия B, каналы (резерв 9), автонейминг; исправить расхождения; проверить `openspec validate init-current-system --strict`
- [ ] 1.3 Сверить дельту `drum-engine` с кодом (`src/session/drum/` или `src/session/model/drum_track.py`): 16 lane GM 36–51, сетка 16/32/48/64, три уровня velocity, preview; исправить расхождения; проверить `openspec validate init-current-system --strict`
- [ ] 1.4 Сверить дельту `mutation` с кодом (`src/session/mutation/`, `src/session/model/version_history.py`, `docs/mutation-manual-spec.md` §11): pending/граница цикла/undo/recall/лимит 256/LED ch 0 и ch 14; исправить расхождения; проверить `openspec validate init-current-system --strict`
- [ ] 1.5 Сверить дельту `clock-sync` с кодом (`src/sync/clock_manager.py`, `tick_proxy.py`, `swing.py`, `transport.py`, `application.py`): квантизация с допуском, watchdog ~0.5 с, MIDI clock out 0xF8 из таймлайна; исправить расхождения; проверить `openspec validate init-current-system --strict`
- [ ] 1.6 Сверить дельту `midi-routing` с кодом (`src/sync/ports.py`, `routing.py`, `port_state.py`, `cc_map.py`, `throttle.py`): статусы портов, hot-plug ~2 c, `ports switch`, троттлинг 30 Гц; исправить расхождения; проверить `openspec validate init-current-system --strict`
- [ ] 1.7 Сверить дельту `push2-ui` с кодом (`src/devices/push2/mapping.py`, `screens.py`, `src/app/ui/`, `src/app/ui/screen_controller.py`): карта CC, NEW/UNDO/Duplicate, VERSIONS, flash, keepalive ~1 c; исправить расхождения; проверить `openspec validate init-current-system --strict`
- [ ] 1.8 Сверить дельту `repl-control` с кодом (`src/repl/`, `src/app/engine_control.py`): список команд, подтверждения y/N, история repl_history, headless SIGTERM RC 0; исправить расхождения; проверить `openspec validate init-current-system --strict`

## 2. Валидация и финализация change

- [ ] 2.1 Прогнать `openspec validate init-current-system` и `openspec status --change init-current-system`: все артефакты done, валидация без ошибок
- [ ] 2.2 Прогнать регрессию проекта (`uv run pytest`): 1830 passed — change не затронул код; линтеры не добавили новых замечаний (`uv run ruff check src tests`, `uv run black --check src tests`, `uv run mypy src` — сравнить с зафиксированной базой: ruff 50, black 11 файлов, mypy 20)

## Workflow follow-up

- Синхронизировать дельты в основные спеки (`openspec sync specs` / скилл openspec-sync-specs) — появляется `openspec/specs/<capability>/spec.md` × 8.
- Либо (альтернатива sync) архивировать change (`openspec archive init-current-system`) — заодно создаёт main-спеки и фиксирует change в `openspec/changes/archive/`.
- После sync/archive обновить указатели в `AGENTS.md` (раздел «Артефакты») и `plans/ROADMAP.md`: baseline-спеки доступны, новые изменения идут дельтами.
- Запустить `graphify update .` — граф не знает про openspec/ (если включён в индекс).
