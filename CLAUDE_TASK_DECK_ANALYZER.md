# Задача: Universal Deck Intelligence для MTG Hunter

Нужно развить идею Commander Deck Analyzer в универсальную систему анализа колод для разных форматов MTG.

Система должна иметь общее аналитическое ядро, работающее для любых поддерживаемых форматов, и дополнительные format-specific профили поверх него.

## Главная идея

Общая архитектура:

```
Deck
  ↓
Format context
  ↓
Card / deck feature extraction
  ↓
Combo + win condition analysis
  ↓
Universal Deck Feature Vector
  ↓
┌───────────────┬──────────────┬──────────────┬───────────────┐
│ Power Engine  │ Salt Engine  │ Efficiency   │ Format Profile│
└───────────────┴──────────────┴──────────────┴───────────────┘
  ↓
Explainable Deck Intelligence Result
```

Universal Deck Analyzer должен работать для Commander, Standard, Pioneer, Modern, Legacy, Vintage, Pauper и других форматов, которые поддерживает MTG Hunter.

Format-specific слой добавляет то, что имеет смысл только в конкретном формате.

Например:

- Commander: Brackets B1–B5, Game Changers, commander dependency, cEDH profile, Rule 0;
- competitive 60-card formats: legality, sideboard context, speed relative to format, interaction density, combo consistency, archetype-specific signals;
- singleton formats: особый вес consistency, tutors и command-zone-like guaranteed resources, если такие есть.

Не пытаться применять Commander Brackets к Modern/Pioneer/Standard.

## Что должен выдавать универсальный анализ

Для любой колоды:

- Power Score 0–100;
- Salt Score 0–100;
- Salt / $;
- профиль колоды по отдельным осям;
- основные win conditions;
- combo profile;
- главные причины результата;
- карты и взаимодействия, сильнее всего влияющие на Power / Salt;
- confidence;
- format-specific analysis.

Для Commander дополнительно:

- ориентировочный Bracket B1 / B2 / B3 / B4 / B5;
- bracket compatibility / violations / warnings;
- Game Changers;
- cEDH / optimized profile;
- commander dependency;
- commander as engine / combo piece.

## Universal metrics

Минимальный общий профиль:

```
Power
Salt
Salt / $
Speed
Consistency
Interaction
Resilience
Mana Acceleration
Tutoring / Selection
Card Advantage
Combo Potential
Win Condition Efficiency
Resource Denial
Lock Potential
```

Часть метрик может иметь разный вес или интерпретацию в разных форматах.

## Universal Deck Feature Vector

Нужно собирать единое представление колоды, включающее как минимум:

- format;
- deck size;
- sideboard / commander / companion / special zones, если применимо;
- mana curve;
- land count;
- mana acceleration;
- fast mana;
- rituals;
- card selection;
- tutors;
- unconditional / broad / narrow tutors;
- card draw;
- recursion;
- protection;
- removal;
- counterspells;
- free interaction;
- sweepers;
- discard;
- stax / taxes;
- resource denial;
- land destruction;
- hard locks;
- extra turns;
- complete combos;
- compact combos;
- deterministic combos;
- win conditions;
- combo accessibility;
- resilience;
- unknown / unresolved cards;
- deck market value.

Для Commander дополнительно:

- commander;
- commander dependency;
- commander as engine;
- commander as combo piece;
- commander-based combos;
- Game Changers.

## Использование существующего MTG Hunter

Анализатор должен использовать существующие возможности проекта, а не создавать параллельные аналоги:

- локальную базу карт;
- Scryfall metadata;
- Scryfall Tagger / card tags;
- Commander Spellbook;
- существующий combo-анализ;
- win routes;
- deck shape;
- goldfish;
- format legality;
- deck storage;
- price data;
- существующие данные о функциях карт.

## Power Score

Power отражает реальную способность колоды выигрывать и навязывать свой план.

Основные факторы:

- speed;
- consistency;
- interaction;
- resilience;
- mana efficiency;
- acceleration;
- tutoring / selection;
- combo accessibility;
- win condition efficiency;
- card advantage;
- quality of threats / engines.

Power нельзя считать простым средним.

Нужно учитывать нелинейные сочетания:

- compact combo + tutors;
- cheap win condition + strong selection;
- fast mana + compact win;
- free interaction + fast plan;
- redundant threats + recursion;
- guaranteed zone resource + combo piece;
- low curve + high card velocity.

Power должен оцениваться в контексте формата.

Например одна и та же скорость может быть очень высокой для Commander и обычной для Legacy.

## Salt Score

Salt отражает не силу как таковую, а насколько стратегия ограничивает других игроков или создаёт субъективно тяжёлый игровой опыт.

Основные сигналы:

- stax;
- taxes;
- hard locks;
- resource denial;
- mass land destruction;
- repeatable discard;
- prison effects;
- repeated / infinite extra turns;
- game monopoly;
- solitaire loops;
- oppressive denial engines.

Важно:

- сильный removal сам по себе не делает деку солёной;
- хорошие counterspells сами по себе не означают высокий Salt;
- высокая сила и высокая соль — разные вещи;
- слабая prison/stax дека может иметь Power 55 и Salt 90;
- быстрая combo дека может иметь Power 92 и Salt 40.

Salt тоже должен учитывать форматный контекст.

То, что считается нормальным interaction package в Legacy, не должно автоматически получать ту же трактовку, что и в casual Commander.

## Salt / $

Добавить отдельную бюджетную метрику: насколько много "соли" дека создаёт на единицу стоимости.

Она не заменяет Salt Score.

Показывать минимум:

```
Deck price: $185
Salt: 78/100
Salt / $: 0.422
Salt / $100: 42.2
```

Базовая идея:

```
salt_per_dollar = salt_score / deck_price_usd
salt_per_100_dollars = salt_score * 100 / deck_price_usd
```

Нужно корректно обрабатывать нулевую/неполную цену и показывать confidence / coverage по стоимости.

Смысл метрики:

- две деки могут иметь Salt 80;
- одна стоит $1200;
- другая $90;
- вторая имеет намного более высокий Salt/$ и является существенно более "экономичной мерзостью".

Цена должна считаться по единой понятной методике, чтобы сравнения были честными.

Нужно явно показывать price basis, например:

- market / cheapest available;
- paper;
- nonfoil by default;
- только карты, для которых удалось получить цену;
- price coverage (%).

Не смешивать стоимость уже имеющейся у пользователя коллекции с market value самой колоды. Salt/$ — характеристика decklist, а не того, сколько конкретный пользователь доплатил за её сборку.

Архитектура должна позволять позже добавить похожие efficiency metrics, например Power/$, но сейчас обязательна именно Salt/$.

## Combo analysis

Combo не должна быть бинарным флагом.

Учитывать:

- число pieces;
- mana requirement;
- deterministic win или нет;
- infinite damage / mana / draw / tokens / loop / lock / value engine;
- redundancy;
- сколько tutors / selection эффектов реально помогают её собрать;
- доступность pieces;
- участие guaranteed-zone cards;
- насколько combo компактна;
- насколько легко её защитить;
- насколько легко восстановиться после disruption.

Нужна отдельная метрика Combo Accessibility / Combo Consistency.

Пример:

```
Combo A + B

pieces: 2
useful tutors: 7
mana requirement: low
deterministic win: yes
guaranteed-zone piece: yes

Accessibility: 92/100
```

Для Commander guaranteed-zone piece обычно означает commander.

## Format context

Результат должен учитывать формат.

Система должна уметь иметь format profile / rule profile, который задаёт:

- legality;
- deck construction rules;
- singleton / non-singleton;
- sideboard rules;
- normal speed range;
- normal interaction density;
- expected consistency;
- allowed / banned / restricted cards;
- special rules;
- format-specific classifiers.

Universal score должен быть сравнимым в общих чертах, но объяснение обязано учитывать format context.

Желательно также иметь format-relative показатели, например:

```
Power: 82/100
Format percentile / relative tier signal: high
Speed relative to Modern: high
Interaction relative to Modern: medium
```

Если надёжных данных для percentile нет, не выдумывать его.

## Commander profile

Commander получает дополнительный слой анализа.

### Bracket Engine

Bracket нельзя получать простым преобразованием Power Score.

Нужно учитывать:

- актуальные Commander Brackets;
- Game Changers;
- bracket restrictions;
- mass land denial;
- extra turns;
- compact intentional infinite combos;
- deck intent;
- optimized profile;
- cEDH profile.

Для каждого bracket желательно возвращать:

```
compatible: true / false
violations: [...]
warnings: [...]
```

Итог:

```
Bracket: B3
Confidence: 86%
Borderline: B3/B4
```

B4 — optimized profile, а не просто "Power > N".

B5 / cEDH — отдельный совокупный профиль, а не любое high-power casual.

### Commander-specific consistency

Учитывать:

- commander всегда доступен;
- commander как engine;
- commander как tutor;
- commander как combo piece;
- combo pieces в command zone;
- dependency on commander.

### Game Changers / rules version

Commander rules и Game Changers должны быть обновляемыми и версионируемыми.

Результат должен показывать версию правил.

## Competitive 60-card format profiles

Для Standard / Pioneer / Modern / Legacy / Vintage / Pauper universal engine остаётся тем же, но format profile должен учитывать особенности формата.

Нужно оценивать по возможности:

- speed относительно формата;
- consistency;
- interaction efficiency;
- threat density;
- card selection;
- combo compactness;
- resilience;
- sideboard relevance;
- mana efficiency;
- dependency on specific pieces;
- vulnerability to common classes of disruption.

Не требуется строить полноценную metagame prediction system, если в проекте нет надёжных metagame data.

Не выдавать выдуманный matchup score без данных.

## Confidence

Любой анализ должен содержать confidence.

Он снижается если:

- неизвестные карты;
- неполная decklist;
- недоступна combo DB;
- отсутствуют tags;
- неизвестен формат;
- низкое price coverage;
- не хватает format-specific данных;
- часть ключевых признаков невозможно классифицировать.

Confidence может быть общей и отдельной для подсистем:

```
overall confidence
power confidence
salt confidence
price confidence
bracket confidence
```

## Explainability

Каждый score должен иметь contributors.

Пример:

```
Power 81:
+ высокая tutor density
+ compact deterministic combo
+ высокий card velocity
+ дешёвая interaction package

Salt 67:
+ hard lock
+ repeatable mana denial
+ extra turn loop

Salt/$ высокий:
+ Salt 67
+ market value deck всего $82
```

## Impact cards

Показывать карты, которые сильнее всего влияют на:

- Power;
- Salt;
- Salt/$;
- format-specific classification;
- Commander Bracket, если применимо.

Пример:

```
Card X
power impact: high
salt impact: low
price impact: high
salt/$ effect: lowers efficiency

Card Y
power impact: medium
salt impact: high
price impact: low
salt/$ effect: strongly increases efficiency
```

## What-if analysis

Архитектура должна позволять сравнивать добавление / удаление / замену карты.

Пример:

```
Before:
Power 74
Salt 61
Price $210
Salt/$100 29.0

After replacing Card A with Card B:
Power 76
Salt 68
Price $165
Salt/$100 41.2
```

Для Commander дополнительно показать изменение bracket profile.

## UI

В deck workflow нужна единая секция Deck Intelligence.

Универсальная часть:

```
Power  ████████░░ 78
Salt   ██████░░░░ 61

Deck value: $185
Salt / $100: 33.0
```

Ниже:

```
Speed
Consistency
Interaction
Resilience
Mana Acceleration
Tutoring / Selection
Card Advantage
Combo
Stax / Denial
```

И секция "Почему такой результат".

Для Commander сверху дополнительно:

```
B3 — Upgraded
Confidence 87%
```

Для других форматов вместо bracket показывается соответствующий format profile.

## Data model

Нужен единый результат, пригодный для UI, тестов и what-if.

Пример:

```json
{
  "format": "commander",
  "power": {
    "score": 78,
    "confidence": 0.91
  },
  "salt": {
    "score": 61,
    "confidence": 0.88
  },
  "price": {
    "usd": 185.0,
    "coverage": 0.97,
    "basis": "paper_nonfoil_market"
  },
  "efficiency": {
    "salt_per_dollar": 0.3297,
    "salt_per_100_dollars": 32.97
  },
  "metrics": {
    "speed": 74,
    "consistency": 86,
    "interaction": 71,
    "resilience": 67,
    "mana_acceleration": 63,
    "tutoring": 88,
    "combo": 91,
    "resource_denial": 24
  },
  "format_profile": {},
  "commander_profile": {
    "bracket": {
      "value": 3,
      "name": "Upgraded",
      "confidence": 0.87,
      "borderline": null
    }
  },
  "reasons": [],
  "impact_cards": [],
  "warnings": []
}
```

Точная внутренняя реализация остаётся на усмотрение исполнителя после изучения текущего проекта.

## Тестирование

Нужны unit tests и реальные deck fixtures для разных форматов.

Проверить как минимум:

1. одинаковая карта/механика может иметь разный контекстный вес в разных форматах;
2. Power и Salt не коррелируют принудительно;
3. removal повышает Power, но почти не повышает Salt;
4. stax / prison повышают Salt заметно;
5. compact combo + tutors повышает consistency / Power;
6. unknown cards уменьшают confidence;
7. неполные цены уменьшают price confidence и не дают ложной точности Salt/$;
8. дешёвая high-salt дека имеет выше Salt/$, чем дорогая дека с тем же Salt;
9. Commander-only параметры не применяются к Modern/Pioneer/Standard;
10. high-power casual Commander не становится автоматически cEDH;
11. non-Commander deck не получает Commander Bracket;
12. анализ graceful-degrades при отсутствии Commander Spellbook / price data.

Реальные fixtures должны включать несколько колод из разных форматов:

- Commander casual;
- Commander upgraded;
- Commander optimized;
- Commander cEDH;
- Commander stax / denial;
- Standard;
- Pioneer;
- Modern;
- Legacy или Vintage;
- Pauper.

Для реальных дек проверять диапазоны и здравый смысл, а не точное равенство score.

## Главное требование к качеству

Система должна отвечать не только:

> "Насколько сильная дека?"

а:

> "Как она выигрывает, насколько быстро и стабильно реализует план, как взаимодействует с противником, насколько ограничивает игру, насколько это типично для её формата, сколько стоит этот игровой профиль и почему система пришла именно к такой оценке."

Для Commander поверх этого нужен ответ:

> "Какому Bracket она соответствует и почему?"

А Salt/$ должен отдельно отвечать:

> "Сколько раздражающего игрового опыта можно купить на один доллар бюджета?"
